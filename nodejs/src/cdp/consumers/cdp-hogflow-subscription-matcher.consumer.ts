import { Message } from 'node-rdkafka'
import { Pool } from 'pg'
import { Counter, Histogram } from 'prom-client'

import { HogFlow, HogFlowAction } from '~/cdp/schema/hogflow'
import { KAFKA_CDP_INTERNAL_EVENTS, KAFKA_EVENTS_JSON, KAFKA_PERSON } from '~/common/config/kafka-topics'
import { KafkaConsumerInterface, RdKafkaConsumerConfig, createKafkaConsumer } from '~/common/kafka/consumer'
import { InternalCaptureEvent } from '~/common/services/internal-capture'
import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'
import { UUIDT } from '~/common/utils/utils'

import { ClickHousePerson, HealthCheckResult, PluginsServerConfig, RawClickHouseEvent, Team } from '../../types'
import { CdpInternalEventSchema } from '../schema'
import {
    hasEventOrActionTarget,
    matchesWaitUntilCondition,
    runFilterBytecode,
} from '../services/hogflows/hogflow-utils'
import { CyclotronPerson, HogFlowInvocationContext, HogFunctionInvocationGlobals, MinimalAppMetric } from '../types'
import {
    convertInternalEventToHogFunctionInvocationGlobals,
    convertToHogFunctionInvocationGlobals,
    getPersonDisplayName,
} from '../utils'
import { convertToHogFunctionFilterGlobal } from '../utils/hog-function-filtering'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'
import { counterParseError } from './metrics'

// A waker only needs signals that arrive after a job parks, never history. auto.offset.reset=latest
// makes a fresh consumer group start at the tip instead of replaying the (unconsumable at prod
// volume) topic backlog. Once the group has committed offsets, both consumer impls resume from them
// regardless of this value — so steady-state recovery is committed-offset resume; latest only governs
// the first bootstrap and offset-loss edge cases (covered by the deferred lag alerting follow-up).
const startAtLatest = { ['auto.offset.reset' as keyof RdKafkaConsumerConfig]: 'latest' as never }

const counterHogflowMatcherCandidatesEvaluated = new Counter({
    name: 'cdp_hogflow_matcher_candidates_evaluated',
    help: 'Parked hogflow jobs the matcher loaded from cyclotron and evaluated against a batch.',
})

const counterHogflowMatcherJobsWoken = new Counter({
    name: 'cdp_hogflow_matcher_jobs_woken',
    help: 'Parked hogflow jobs the matcher woke because an incoming event matched.',
})

const counterHogflowMatcherConversionsCounted = new Counter({
    name: 'cdp_hogflow_matcher_conversions_counted',
    help: 'Event-based conversions counted by the matcher (deduped to once per run via conversionCounted).',
})

// Latency of the cyclotron lookup for parked jobs. Watch this for cyclotron-node
// read pressure as the wait-until-event feature ramps.
const histogramHogflowMatcherFindParkedJobs = new Histogram({
    name: 'cdp_hogflow_matcher_find_parked_jobs_seconds',
    help: 'Duration of the findParkedJobs cyclotron query.',
    labelNames: ['stream'],
    buckets: [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5],
})

// Which Kafka stream a batch came from. Labels the find_parked_jobs metric so the person and
// internal-event query load is distinguishable from the events firehose on the shared cyclotron DB.
type WakeSource = 'events' | 'person' | 'internal_events'

const counterHogflowMatcherEventSkipped = new Counter({
    name: 'cdp_hogflow_matcher_event_skipped',
    help: 'An incoming event was dropped before matching: no identifiers (distinct_id or person_id), or unknown team.',
    labelNames: ['reason'],
})

type ParkedCandidate = {
    id: string
    teamId: number
    functionId: string
    parentRunId: string | null
    actionId: string | null
    distinctId: string | null
    personId: string | null
}

// A parked job the matcher needs to act on this batch: either resume it (stepMatched, or a
// conversion match on an exit-on-conversion flow) and/or count its conversion once. Carries the
// fields needed to emit the `conversion` metric without re-reading the hogflow.
type MatchedJob = {
    id: string
    teamId: number
    functionId: string
    parentRunId: string | null
    stepMatched: boolean
    conversionMatched: boolean
    exitsOnConversion: boolean
    // Name, UUID and timestamp of the matched event, so the resume log can name it and link to it.
    eventName?: string
    eventUuid?: string
    eventTimestamp?: string
    // Distinct id + name/uuid of the event that satisfied the conversion goal, so the matcher can
    // emit the `$workflows_conversion` PostHog event for the converting person.
    conversionDistinctId?: string
    conversionEventName?: string
    conversionEventUuid?: string
    // Set when a $task_run_completed internal event matched a parked agent_task step by distinct_id.
    // The task run id is confirmed against the job's stored id under FOR UPDATE before waking, since
    // many jobs can share a distinct_id.
    agentTask?: AgentTaskCompletion
}

type AgentTaskCompletion = {
    taskRunId: string
    status: string
    output: unknown
}

// Payload for capturedEventsService.queueEvent — a resolved PostHog capture event minus the token.
type CapturedConversionEvent = { team_id: number } & Omit<InternalCaptureEvent, 'team_token'>

type FilterGlobals = ReturnType<typeof convertToHogFunctionFilterGlobal>

// Wakes parked hogflow jobs when an event matches a `wait_until_condition` step
// or a workflow conversion goal.
export class CdpHogflowSubscriptionMatcherConsumer<
    TConfig extends PluginsServerConfig = PluginsServerConfig,
> extends CdpConsumerBase<TConfig> {
    protected name = 'CdpHogflowSubscriptionMatcherConsumer'
    protected kafkaConsumer: KafkaConsumerInterface
    // clickhouse_person carries non-event person-property changes (the precalculated topic only
    // emits a per-condition match boolean, not the full property set the wait bytecode needs).
    private personKafkaConsumer: KafkaConsumerInterface
    // cdp_internal_events carries CDP-generated signals (e.g. $insight_alert_firing,
    // $activity_log_entry_created) that bypass the public capture pipeline and never reach the
    // analytics events topic. (Email engagement events, by contrast, flow through capture to
    // clickhouse_events_json and are already covered by the events stream.)
    private internalEventsKafkaConsumer: KafkaConsumerInterface
    private cyclotronPool: Pool

    constructor(config: TConfig, deps: CdpConsumerBaseDeps) {
        super(config, deps)
        this.kafkaConsumer = createKafkaConsumer(
            {
                groupId: 'cdp-hogflow-subscription-matcher-consumer',
                topic: KAFKA_EVENTS_JSON,
            },
            startAtLatest
        )
        this.personKafkaConsumer = createKafkaConsumer(
            {
                groupId: 'cdp-hogflow-subscription-matcher-person-consumer',
                topic: KAFKA_PERSON,
            },
            startAtLatest
        )
        this.internalEventsKafkaConsumer = createKafkaConsumer(
            {
                groupId: 'cdp-hogflow-subscription-matcher-internal-events-consumer',
                topic: KAFKA_CDP_INTERNAL_EVENTS,
            },
            startAtLatest
        )

        // The matcher does nothing but read/write cyclotron_jobs, so a missing connection
        // string means it would silently consume the event stream and wake nothing. Fail
        // loudly on startup instead of degrading into a healthy-looking no-op.
        if (!config.CYCLOTRON_NODE_DATABASE_URL) {
            throw new Error('CdpHogflowSubscriptionMatcherConsumer requires CYCLOTRON_NODE_DATABASE_URL')
        }
        this.cyclotronPool = new Pool({
            connectionString: config.CYCLOTRON_NODE_DATABASE_URL,
            max: config.CYCLOTRON_NODE_MAX_CONNECTIONS,
        })
    }

    public async processBatch(
        invocationGlobals: HogFunctionInvocationGlobals[],
        source: WakeSource = 'events'
    ): Promise<void> {
        if (!invocationGlobals.length) {
            return
        }
        try {
            await this.wakeMatchingWorkflows(invocationGlobals, source)
        } finally {
            // Flush any `conversion` metrics and `$workflows_conversion` events queued during matching.
            // Best-effort: a flush failure must not crash the batch (which would replay the event
            // offsets). flush() is a no-op when nothing was queued, so it's safe to call unconditionally.
            await instrumentFn({ key: 'cdp.background_task.monitoring_flush', sendException: false }, async () => {
                try {
                    await Promise.all([
                        this.hogFunctionMonitoringService.flush(),
                        this.invocationResultsService.capturedEventsService.flush(),
                    ])
                } catch (err) {
                    logger.error('⚠️', 'Failed to flush hogflow matcher app metrics/events', { err })
                    captureException(err)
                }
            })
        }
    }

    @instrumented('cdpHogflowSubscriptionMatcher.wakeMatchingWorkflows')
    private async wakeMatchingWorkflows(
        invocationGlobals: HogFunctionInvocationGlobals[],
        source: WakeSource = 'events'
    ): Promise<void> {
        const { teamIds, distinctTeamIds, distinctIds, personTeamIds, personIds, byDistinctId, byPersonId } =
            indexBatch(invocationGlobals)
        if (byDistinctId.size === 0 && byPersonId.size === 0) {
            return
        }

        // Build the set of actionable flows from the in-memory hogflow cache (same pattern as
        // cdp-events). Only flows with a wait_until_condition step or an event-based conversion
        // goal can ever be woken; scoping to them keeps the function_id list in findParkedJobs
        // small and skips cyclotron entirely when a batch has none.
        const hogFlowsByTeam = await this.hogFlowManager.getHogFlowsForTeams(teamIds)
        const hogflows: Record<string, HogFlow> = {}
        for (const flows of Object.values(hogFlowsByTeam)) {
            for (const flow of flows) {
                if (isActionableFlow(flow, source)) {
                    hogflows[flow.id] = flow
                }
            }
        }

        if (Object.keys(hogflows).length === 0) {
            return
        }

        const candidates = await this.findParkedJobs(
            distinctTeamIds,
            distinctIds,
            personTeamIds,
            personIds,
            Object.keys(hogflows),
            source
        )
        if (candidates.length === 0) {
            return
        }
        counterHogflowMatcherCandidatesEvaluated.inc(candidates.length)

        // Compute filterGlobals once per event; the same event can match many candidates.
        const filterGlobalsByEvent = new Map<HogFunctionInvocationGlobals, FilterGlobals>()
        const filterGlobalsFor = (g: HogFunctionInvocationGlobals): FilterGlobals => {
            let fg = filterGlobalsByEvent.get(g)
            if (!fg) {
                fg = convertToHogFunctionFilterGlobal(g)
                filterGlobalsByEvent.set(g, fg)
            }
            return fg
        }

        const matchedJobs: MatchedJob[] = []
        for (const candidate of candidates) {
            const hogflow = hogflows[candidate.functionId]
            if (!hogflow) {
                continue
            }

            const candidateGlobals = collectCandidateGlobals(candidate, byDistinctId, byPersonId)
            if (candidateGlobals.length === 0) {
                continue
            }

            const action = candidate.actionId
                ? hogflow.actions.find((a: HogFlowAction) => a.id === candidate.actionId)
                : undefined

            // Any single matching event is enough. Stop early once both flags are set.
            let stepMatched = false
            let stepMatchedEventName: string | undefined
            let stepMatchedEventUuid: string | undefined
            let stepMatchedEventTimestamp: string | undefined
            let conversionMatched = false
            let conversionDistinctId: string | undefined
            let conversionEventName: string | undefined
            let conversionEventUuid: string | undefined
            let agentTask: AgentTaskCompletion | undefined
            for (const globals of candidateGlobals) {
                const filterGlobals = filterGlobalsFor(globals)
                // agent_task steps wake on a $task_run_completed internal event, not on filter bytecode.
                // The task run id is confirmed against the parked job's stored id in applyMatchToState.
                if (!agentTask && action?.type === 'agent_task') {
                    agentTask = extractAgentTaskCompletion(globals.event)
                }
                if (!stepMatched && action?.type === 'wait_until_condition') {
                    if (
                        await matchesWaitUntilCondition(action, filterGlobals, {
                            hogFlowId: hogflow.id,
                            actionId: action.id,
                        })
                    ) {
                        stepMatched = true
                        stepMatchedEventName = globals.event.event
                        stepMatchedEventUuid = globals.event.uuid
                        stepMatchedEventTimestamp = globals.event.timestamp
                    }
                }
                if (!conversionMatched && (await this.evaluateConversionEvents(hogflow, filterGlobals))) {
                    conversionMatched = true
                    // Remember who converted (and via which event) so we can emit $workflows_conversion.
                    conversionDistinctId = globals.event.distinct_id
                    conversionEventName = globals.event.event
                    conversionEventUuid = globals.event.uuid
                }
                if (stepMatched && conversionMatched) {
                    break
                }
            }

            // Collect a job when its wait step matched OR a conversion matched. Conversion matches are
            // collected even on measurement-only (non-exit) flows: processMatchedJobs reads the job's
            // state under FOR UPDATE to count the conversion exactly once per run (and surface it to
            // the executor for exit-on-conversion flows). The wake-vs-count-only decision is made there.
            if (stepMatched || conversionMatched || agentTask) {
                matchedJobs.push({
                    id: candidate.id,
                    teamId: candidate.teamId,
                    functionId: candidate.functionId,
                    parentRunId: candidate.parentRunId,
                    stepMatched,
                    conversionMatched,
                    exitsOnConversion: exitsOnConversion(hogflow),
                    eventName: stepMatchedEventName,
                    eventUuid: stepMatchedEventUuid,
                    eventTimestamp: stepMatchedEventTimestamp,
                    conversionDistinctId,
                    conversionEventName,
                    conversionEventUuid,
                    agentTask,
                })
            }
        }

        if (matchedJobs.length === 0) {
            return
        }

        const { woken, conversionsCounted } = await this.processMatchedJobs(matchedJobs)
        counterHogflowMatcherJobsWoken.inc(woken)
        counterHogflowMatcherConversionsCounted.inc(conversionsCounted)
        logger.info('⚡', 'Processed waiting workflows from event match', {
            evaluated: candidates.length,
            matched: matchedJobs.length,
            woken,
            conversionsCounted,
        })
    }

    private async evaluateConversionEvents(hogflow: HogFlow, filterGlobals: FilterGlobals): Promise<boolean> {
        const conversionEvents = hogflow.conversion?.events ?? []
        const context = { hogFlowId: hogflow.id }
        for (const eventConfig of conversionEvents) {
            if (!hasEventOrActionTarget(eventConfig)) {
                continue
            }
            if (await runFilterBytecode(eventConfig.filters?.bytecode, filterGlobals, context)) {
                return true
            }
        }
        return false
    }

    private async findParkedJobs(
        distinctTeamIds: number[],
        distinctIds: string[],
        personTeamIds: number[],
        personIds: string[],
        functionIds: string[],
        source: WakeSource
    ): Promise<ParkedCandidate[]> {
        // Two index-friendly branches with UNION (dedupes rows that match both keys).
        // A single OR across distinct_id and person_id often forces Postgres into a
        // sequential scan; splitting lets each branch hit its own composite index.
        // Each branch correlates (team_id, id) as a tuple via `unnest(teams, ids)`, which
        // zips the parallel arrays row-wise — a job only matches when its team and its id
        // came from the SAME event. Filtering team_id and distinct_id independently with
        // ANY/ANY would match a job whose team and distinct_id came from two different
        // events in the batch (a cross-team false-positive candidate). The function_id
        // filter further scopes to flows the matcher can act on.
        //
        // We deliberately do NOT filter by queue_name: a parked wait can sit on a queue
        // other than 'hogflow'. When a step (e.g. email) routes the invocation to a
        // dedicated queue, the following wait parks on that queue, so a queue_name='hogflow'
        // filter would silently miss it. function_id already scopes to hogflow jobs, and
        // waking the job (scheduled = NOW()) lets whichever worker owns that queue resume it.
        const stopTimer = histogramHogflowMatcherFindParkedJobs.startTimer({ stream: source })
        let result
        try {
            result = await this.cyclotronPool.query(
                `SELECT id, team_id, function_id, parent_run_id, action_id, distinct_id, person_id
             FROM cyclotron_jobs
             WHERE status = 'available'
               AND scheduled > NOW()
               AND function_id = ANY($5::uuid[])
               AND (team_id, distinct_id) IN (SELECT * FROM unnest($1::int[], $2::text[]))
             UNION
             SELECT id, team_id, function_id, parent_run_id, action_id, distinct_id, person_id
             FROM cyclotron_jobs
             WHERE status = 'available'
               AND scheduled > NOW()
               AND function_id = ANY($5::uuid[])
               AND (team_id, person_id) IN (SELECT * FROM unnest($3::int[], $4::text[]))`,
                [distinctTeamIds, distinctIds, personTeamIds, personIds, functionIds]
            )
        } finally {
            stopTimer()
        }

        return result.rows.map((row) => ({
            id: row.id,
            teamId: row.team_id,
            functionId: row.function_id,
            parentRunId: row.parent_run_id,
            actionId: row.action_id,
            distinctId: row.distinct_id,
            personId: row.person_id,
        }))
    }

    private async processMatchedJobs(matched: MatchedJob[]): Promise<{ woken: number; conversionsCounted: number }> {
        if (matched.length === 0) {
            return { woken: 0, conversionsCounted: 0 }
        }

        const ids = matched.map((m) => m.id)
        // The state read-modify-write must be atomic: two matcher instances acting on the same job
        // would otherwise both read the original state and the later UPDATE would drop the earlier
        // flag — and both would count the same conversion. SELECT ... FOR UPDATE inside a transaction
        // serializes them: the second instance blocks, then reads our committed `conversionCounted`
        // and skips the duplicate. ORDER BY id keeps lock acquisition order consistent across
        // instances so concurrent batches can't deadlock.
        const client = await this.cyclotronPool.connect()
        try {
            await client.query('BEGIN')

            const stateRows = await client.query(
                `SELECT id, state FROM cyclotron_jobs
                 WHERE id = ANY($1::uuid[]) AND status = 'available'
                 ORDER BY id
                 FOR UPDATE`,
                [ids]
            )

            const matchedById = new Map(matched.map((m) => [m.id, m]))
            // Woken jobs get `scheduled = NOW()`; count-only jobs (measurement-only conversions on
            // non-exit flows) get a state write that leaves `scheduled` untouched, so we persist
            // `conversionCounted` without pulling a parked job forward.
            const wakeUpdates: { id: string; state: Buffer }[] = []
            const stateOnlyUpdates: { id: string; state: Buffer }[] = []
            const conversionMetrics: MinimalAppMetric[] = []
            const conversionEvents: CapturedConversionEvent[] = []
            for (const row of stateRows.rows) {
                if (!row.state) {
                    continue
                }
                const m = matchedById.get(row.id)
                if (!m) {
                    continue
                }
                const outcome = applyMatchToState(row.state, m)
                if (!outcome) {
                    continue
                }
                if (outcome.countConversion) {
                    conversionMetrics.push({
                        team_id: m.teamId,
                        // Key by the run id so batch-workflow conversions land under the batch job
                        // (parentRunId), matching how the executor records property-based conversions.
                        app_source_id: m.parentRunId ?? m.functionId,
                        instance_id: m.functionId,
                        metric_kind: 'other',
                        metric_name: 'conversion',
                        count: 1,
                    })
                    // Emit the same billable $workflows_conversion event as the executor's property
                    // path, so event-based conversions also power insights/cohorts. Needs a
                    // distinct_id to attribute to a person.
                    if (m.conversionDistinctId) {
                        conversionEvents.push({
                            team_id: m.teamId,
                            event: '$workflows_conversion',
                            distinct_id: m.conversionDistinctId,
                            timestamp: new Date().toISOString(),
                            properties: {
                                $workflow_id: m.functionId,
                                $workflow_conversion_type: 'event',
                                $workflow_conversion_event: m.conversionEventName,
                                $workflow_conversion_event_uuid: m.conversionEventUuid,
                            },
                        })
                    }
                }
                if (outcome.wake) {
                    wakeUpdates.push({ id: row.id, state: outcome.state })
                } else {
                    stateOnlyUpdates.push({ id: row.id, state: outcome.state })
                }
            }

            let woken = 0
            if (wakeUpdates.length > 0) {
                const result = await client.query(
                    `UPDATE cyclotron_jobs cj
                     SET scheduled = NOW(), state = u.state
                     FROM (
                         SELECT unnest($1::uuid[]) AS id, unnest($2::bytea[]) AS state
                     ) u
                     WHERE cj.id = u.id AND cj.status = 'available'`,
                    [wakeUpdates.map((u) => u.id), wakeUpdates.map((u) => u.state)]
                )
                woken = result.rowCount ?? 0
            }
            if (stateOnlyUpdates.length > 0) {
                await client.query(
                    `UPDATE cyclotron_jobs cj
                     SET state = u.state
                     FROM (
                         SELECT unnest($1::uuid[]) AS id, unnest($2::bytea[]) AS state
                     ) u
                     WHERE cj.id = u.id AND cj.status = 'available'`,
                    [stateOnlyUpdates.map((u) => u.id), stateOnlyUpdates.map((u) => u.state)]
                )
            }
            await client.query('COMMIT')

            // Queue metrics/events only after the dedup write commits: if the transaction rolled back,
            // the run is still uncounted in state, so a retry must be free to count it (no double-count).
            for (const metric of conversionMetrics) {
                this.hogFunctionMonitoringService.queueAppMetric(metric, 'hog_flow')
            }
            await Promise.all(
                conversionEvents.map((event) => this.invocationResultsService.capturedEventsService.queueEvent(event))
            )
            return { woken, conversionsCounted: conversionMetrics.length }
        } catch (err) {
            await client.query('ROLLBACK').catch(() => {})
            throw err
        } finally {
            client.release()
        }
    }

    @instrumented('cdpHogflowSubscriptionMatcher.parseKafkaMessages')
    public async _parseKafkaBatch(messages: Message[]): Promise<HogFunctionInvocationGlobals[]> {
        const events: HogFunctionInvocationGlobals[] = []

        await Promise.all(
            messages.map(async (message) => {
                try {
                    const clickHouseEvent = parseJSON(message.value!.toString()) as RawClickHouseEvent
                    // A job can be parked by distinct_id or person_id, so an event needs at least
                    // one of them to match anything. Drop only events that carry neither.
                    if (!clickHouseEvent.person_id && !clickHouseEvent.distinct_id) {
                        counterHogflowMatcherEventSkipped.labels({ reason: 'no_identifiers' }).inc()
                        return
                    }
                    // The vast majority of events belong to teams with no wait_until_condition
                    // step and no event conversion goal. Bail on those via the in-memory hogflow
                    // cache before paying for getTeam + full globals conversion.
                    const teamHogFlows = await this.hogFlowManager.getHogFlowsForTeam(clickHouseEvent.team_id)
                    if (!teamHogFlows.some(hasWaitUntilOrConversion)) {
                        counterHogflowMatcherEventSkipped.labels({ reason: 'no_actionable_flow' }).inc()
                        return
                    }
                    const team = await this.deps.teamManager.getTeam(clickHouseEvent.team_id)
                    if (!team) {
                        counterHogflowMatcherEventSkipped.labels({ reason: 'no_team' }).inc()
                        return
                    }
                    events.push(convertToHogFunctionInvocationGlobals(clickHouseEvent, team, this.config.SITE_URL))
                } catch (e) {
                    logger.error('Error parsing message', e)
                    counterParseError.labels({ error: e.message }).inc()
                }
            })
        )

        return events
    }

    @instrumented('cdpHogflowSubscriptionMatcher.parsePersonMessages')
    public async _parsePersonBatch(messages: Message[]): Promise<HogFunctionInvocationGlobals[]> {
        const events: HogFunctionInvocationGlobals[] = []

        await Promise.all(
            messages.map(async (message) => {
                try {
                    const data = parseJSON(message.value!.toString()) as ClickHousePerson
                    // A deleted person can never satisfy a wait — skip tombstones.
                    if (data.is_deleted) {
                        return
                    }
                    // Parked waits are matched by person_id (the job's person.id), so a person
                    // mutation needs an id to wake anything.
                    if (!data.id) {
                        counterHogflowMatcherEventSkipped.labels({ reason: 'no_identifiers' }).inc()
                        return
                    }
                    // clickhouse_person is a firehose; bail before getTeam + JSON parse for teams
                    // with no flow the matcher can act on.
                    const teamHogFlows = await this.hogFlowManager.getHogFlowsForTeam(data.team_id)
                    if (!teamHogFlows.some(hasWaitUntilOrConversion)) {
                        counterHogflowMatcherEventSkipped.labels({ reason: 'no_actionable_flow' }).inc()
                        return
                    }
                    const team = await this.deps.teamManager.getTeam(data.team_id)
                    if (!team) {
                        counterHogflowMatcherEventSkipped.labels({ reason: 'no_team' }).inc()
                        return
                    }
                    events.push(convertClickhousePersonToWakeGlobals(data, team, this.config.SITE_URL))
                } catch (e) {
                    logger.error('Error parsing person message', e)
                    counterParseError.labels({ error: e.message }).inc()
                }
            })
        )

        return events
    }

    @instrumented('cdpHogflowSubscriptionMatcher.parseInternalEventMessages')
    public async _parseInternalEventsBatch(messages: Message[]): Promise<HogFunctionInvocationGlobals[]> {
        const events: HogFunctionInvocationGlobals[] = []

        await Promise.all(
            messages.map(async (message) => {
                try {
                    const parsed = CdpInternalEventSchema.parse(parseJSON(message.value!.toString()))
                    if (!parsed.event.distinct_id && !parsed.person?.id) {
                        counterHogflowMatcherEventSkipped.labels({ reason: 'no_identifiers' }).inc()
                        return
                    }
                    const teamHogFlows = await this.hogFlowManager.getHogFlowsForTeam(parsed.team_id)
                    // Internal events can wake agent_task steps too, so include those flows here.
                    if (!teamHogFlows.some((flow) => isActionableFlow(flow, 'internal_events'))) {
                        counterHogflowMatcherEventSkipped.labels({ reason: 'no_actionable_flow' }).inc()
                        return
                    }
                    const team = await this.deps.teamManager.getTeam(parsed.team_id)
                    if (!team) {
                        counterHogflowMatcherEventSkipped.labels({ reason: 'no_team' }).inc()
                        return
                    }
                    events.push(convertInternalEventToHogFunctionInvocationGlobals(parsed, team, this.config.SITE_URL))
                } catch (e) {
                    logger.error('Error parsing internal event message', e)
                    counterParseError.labels({ error: e.message }).inc()
                }
            })
        )

        return events
    }

    public override async start(): Promise<void> {
        await super.start()
        // Surface failures to each kafka consumer so the offset doesn't advance past a batch we
        // couldn't match. The pod will crash and replay; the SELECT is read-only and the UPDATE
        // (with `status = 'available'` guards) is idempotent, so replay is safe. All three streams
        // funnel into the same input-agnostic wakeMatchingWorkflows via processBatch.
        await Promise.all([
            this.kafkaConsumer.connect(async (messages) => {
                return await instrumentFn('cdpHogflowSubscriptionMatcher.handleEachBatch', async () => {
                    return { backgroundTask: this.processBatch(await this._parseKafkaBatch(messages), 'events') }
                })
            }),
            this.personKafkaConsumer.connect(async (messages) => {
                return await instrumentFn('cdpHogflowSubscriptionMatcher.handlePersonBatch', async () => {
                    return { backgroundTask: this.processBatch(await this._parsePersonBatch(messages), 'person') }
                })
            }),
            this.internalEventsKafkaConsumer.connect(async (messages) => {
                return await instrumentFn('cdpHogflowSubscriptionMatcher.handleInternalEventsBatch', async () => {
                    return {
                        backgroundTask: this.processBatch(
                            await this._parseInternalEventsBatch(messages),
                            'internal_events'
                        ),
                    }
                })
            }),
        ])
    }

    public override async stop(): Promise<void> {
        logger.info('💤', `Stopping ${this.name}...`)
        await Promise.all([
            this.kafkaConsumer.disconnect(),
            this.personKafkaConsumer.disconnect(),
            this.internalEventsKafkaConsumer.disconnect(),
        ])
        await this.cyclotronPool.end()
        await super.stop()
        logger.info('💤', `${this.name} stopped!`)
    }

    public isHealthy(): HealthCheckResult {
        // Unhealthy if any stream is unhealthy: with polling gone, a stalled stream means dropped wakes.
        const results = [
            this.kafkaConsumer.isHealthy(),
            this.personKafkaConsumer.isHealthy(),
            this.internalEventsKafkaConsumer.isHealthy(),
        ]
        return results.find((r) => r.status !== 'ok') ?? results[0]
    }
}

// Person mutations arrive on clickhouse_person with the full current property set but no triggering
// analytics event. We synthesize a `$person_updated` event so wakeMatchingWorkflows can run a wait's
// property condition against the new person.properties. Event-name `events` entries never match this
// synthetic event name, which is correct: a person change should only satisfy property-based waits.
function convertClickhousePersonToWakeGlobals(
    data: ClickHousePerson,
    team: Team,
    siteUrl: string
): HogFunctionInvocationGlobals {
    const projectUrl = `${siteUrl}/project/${team.id}`
    const properties = parseJSON(data.properties) as Record<string, any>
    const person: CyclotronPerson = {
        id: data.id,
        properties,
        name: getPersonDisplayName(team, data.id, properties),
        url: `${projectUrl}/person/${encodeURIComponent(data.id)}`,
    }
    return {
        project: { id: team.id, name: team.name, url: projectUrl },
        event: {
            uuid: new UUIDT().toString(),
            event: '$person_updated',
            // Empty so indexBatch only keys this on person_id. A person mutation has no triggering
            // distinct_id, and using the person UUID here would add a spurious (team_id, distinct_id)
            // lookup that matches a job only if its distinct_id happened to equal the UUID.
            distinct_id: '',
            properties: {},
            timestamp: data.timestamp,
            url: person.url,
            elements_chain: '',
        },
        person,
    }
}

type IndexedBatch = {
    teamIds: number[]
    // Parallel (teamId, id) pair arrays for the correlated lookup (see findParkedJobs).
    distinctTeamIds: number[]
    distinctIds: string[]
    personTeamIds: number[]
    personIds: string[]
    byDistinctId: Map<string, HogFunctionInvocationGlobals[]>
    byPersonId: Map<string, HogFunctionInvocationGlobals[]>
}

// Whether a workflow exits when its conversion goal is met. Only then does the matcher wake a
// parked job on a conversion match (so it can exit early); otherwise the conversion goal is
// measurement-only and must not perturb the job's progression.
function exitsOnConversion(hogflow: HogFlow): boolean {
    return (
        hogflow.exit_condition === 'exit_on_conversion' ||
        hogflow.exit_condition === 'exit_on_trigger_not_matched_or_conversion'
    )
}

// Skip teams whose hogflows have nothing the matcher can act on: no wait_until_condition step, and
// no event-based conversion goal. Event conversions are evaluated regardless of exit condition so
// the `conversion` metric is tracked even for flows that don't exit on conversion — only the *wake*
// decision (in wakeMatchingWorkflows) still depends on exitsOnConversion.
function hasWaitUntilOrConversion(hogflow: HogFlow): boolean {
    if (hogflow.actions.some((a: HogFlowAction) => a.type === 'wait_until_condition')) {
        return true
    }
    const conversionEvents = hogflow.conversion?.events
    return Array.isArray(conversionEvents) && conversionEvents.length > 0
}

// The internal-events stream can also wake agent_task steps ($task_run_completed). Those never
// arrive on the events/person firehoses, so only broaden the gate for that source — the firehose
// paths stay scoped to wait/conversion flows and pay no extra cyclotron lookups.
function isActionableFlow(hogflow: HogFlow, source: WakeSource): boolean {
    if (hasWaitUntilOrConversion(hogflow)) {
        return true
    }
    return source === 'internal_events' && hogflow.actions.some((a: HogFlowAction) => a.type === 'agent_task')
}

// A $task_run_completed internal event carries the run id, terminal status and structured output as
// properties. Returns the completion payload when the event is one, else undefined.
function extractAgentTaskCompletion(event: HogFunctionInvocationGlobals['event']): AgentTaskCompletion | undefined {
    if (event.event !== '$task_run_completed') {
        return undefined
    }
    const taskRunId = event.properties?.task_run_id
    if (typeof taskRunId !== 'string' || !taskRunId) {
        return undefined
    }
    return {
        taskRunId,
        status: typeof event.properties?.status === 'string' ? event.properties.status : 'completed',
        output: event.properties?.output,
    }
}

// Single pass over the batch: dedup distinct/person ids, collect team ids,
// and bucket every event under all the keys it could match a candidate by.
function indexBatch(invocationGlobals: HogFunctionInvocationGlobals[]): IndexedBatch {
    const teamIds = new Set<number>()
    const distinctTeamIds: number[] = []
    const distinctIds: string[] = []
    const personTeamIds: number[] = []
    const personIds: string[] = []
    const byDistinctId = new Map<string, HogFunctionInvocationGlobals[]>()
    const byPersonId = new Map<string, HogFunctionInvocationGlobals[]>()

    for (const globals of invocationGlobals) {
        const teamId = globals.project.id
        teamIds.add(teamId)

        const distinctId = globals.event.distinct_id
        if (distinctId) {
            const key = `${teamId}:${distinctId}`
            if (!byDistinctId.has(key)) {
                distinctTeamIds.push(teamId)
                distinctIds.push(distinctId)
            }
            pushToMap(byDistinctId, key, globals)
        }
        const personId = globals.person?.id
        if (personId) {
            const key = `${teamId}:${personId}`
            if (!byPersonId.has(key)) {
                personTeamIds.push(teamId)
                personIds.push(personId)
            }
            pushToMap(byPersonId, key, globals)
        }
    }

    return {
        teamIds: [...teamIds],
        distinctTeamIds,
        distinctIds,
        personTeamIds,
        personIds,
        byDistinctId,
        byPersonId,
    }
}

function pushToMap<K, V>(map: Map<K, V[]>, key: K, value: V): void {
    const existing = map.get(key)
    if (existing) {
        existing.push(value)
    } else {
        map.set(key, [value])
    }
}

function collectCandidateGlobals(
    candidate: ParkedCandidate,
    byDistinctId: Map<string, HogFunctionInvocationGlobals[]>,
    byPersonId: Map<string, HogFunctionInvocationGlobals[]>
): HogFunctionInvocationGlobals[] {
    const seen = new Set<HogFunctionInvocationGlobals>()
    if (candidate.distinctId) {
        for (const g of byDistinctId.get(`${candidate.teamId}:${candidate.distinctId}`) ?? []) {
            seen.add(g)
        }
    }
    if (candidate.personId) {
        for (const g of byPersonId.get(`${candidate.teamId}:${candidate.personId}`) ?? []) {
            seen.add(g)
        }
    }
    return [...seen]
}

type MatchOutcome = { state: Buffer; wake: boolean; countConversion: boolean }

// Applies a batch match to a parked job's state. Returns the new state plus whether the job should
// be woken (`scheduled = NOW()`) and whether its conversion should be counted this run. Returns null
// when nothing changed (e.g. the conversion was already counted and there's no wake to apply).
function applyMatchToState(stateBuffer: Buffer, m: MatchedJob): MatchOutcome | null {
    try {
        const parsed = parseJSON(stateBuffer.toString('utf-8'))
        const updatedState: HogFlowInvocationContext = { ...parsed.state }

        let changed = false
        let wake = false
        let countConversion = false

        // Count each run's conversion at most once, regardless of exit condition. The same flag is
        // set by the executor's property-based path, so a run is counted once whether it converts via
        // a property change or a conversion event — and repeated conversion events no longer inflate
        // the count for measurement-only (non-exit) flows.
        if (m.conversionMatched && !updatedState.conversionCounted) {
            updatedState.conversionCounted = true
            changed = true
            countConversion = true
        }

        // A matched wait_until_condition step resumes the job, tagged so the resume reads as an event
        // match rather than a timeout.
        if (m.stepMatched) {
            if (updatedState.currentAction) {
                updatedState.currentAction = {
                    ...updatedState.currentAction,
                    eventMatched: true,
                    eventMatchedEvent: m.eventName,
                    eventMatchedEventUuid: m.eventUuid,
                    eventMatchedEventTimestamp: m.eventTimestamp,
                }
                changed = true
                wake = true
            } else {
                // A parked wait_until_condition job should always carry its current action. Without it
                // we cannot tag the wake as an event match - skip the flag and continue, since the
                // conversion handling above is independent of currentAction and may still apply.
                logger.warn('Skipping eventMatched: no currentAction in state', { jobId: m.id })
            }
        }

        // A $task_run_completed event resumes a parked agent_task step, but only the job whose stored
        // task run id matches — jobs that merely share the distinct_id are left parked.
        if (m.agentTask) {
            const agentTaskState = updatedState.currentAction?.agentTaskState
            if (agentTaskState && agentTaskState.taskRunId === m.agentTask.taskRunId && !agentTaskState.completed) {
                updatedState.currentAction!.agentTaskState = {
                    ...agentTaskState,
                    completed: true,
                    status: m.agentTask.status,
                    output: m.agentTask.output,
                }
                changed = true
                wake = true
            }
        }

        // Only exit-on-conversion flows resume on a conversion match (so shouldExitEarly can exit).
        // For any other exit condition the conversion is measurement-only: we persist conversionCounted
        // above but must not reschedule, or we'd pull a parked job (e.g. one in a delay) forward.
        if (m.conversionMatched && m.exitsOnConversion) {
            updatedState.conversionMatched = true
            changed = true
            wake = true
        }

        if (!changed) {
            return null
        }
        parsed.state = updatedState
        return { state: Buffer.from(JSON.stringify(parsed)), wake, countConversion }
    } catch (err) {
        logger.warn('Failed to parse state during match', { jobId: m.id, err })
        return null
    }
}
