import { Message } from 'node-rdkafka'
import { Pool } from 'pg'
import { Counter, Histogram } from 'prom-client'

import { HogFlow, HogFlowAction } from '~/cdp/schema/hogflow'
import { KAFKA_EVENTS_JSON } from '~/common/config/kafka-topics'
import { KafkaConsumerInterface, RdKafkaConsumerConfig, createKafkaConsumer } from '~/common/kafka/consumer'
import { InternalCaptureEvent } from '~/common/services/internal-capture'
import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'

import { HealthCheckResult, PluginsServerConfig, RawClickHouseEvent } from '../../types'
import { isEvaluableCondition } from '../services/hogflows/hogflow-utils'
import { HogFlowInvocationContext, HogFunctionInvocationGlobals, MinimalAppMetric } from '../types'
import { convertToHogFunctionInvocationGlobals } from '../utils'
import { execHog } from '../utils/hog-exec'
import { convertToHogFunctionFilterGlobal } from '../utils/hog-function-filtering'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'
import { counterParseError } from './metrics'

const counterHogflowMatcherBytecodeError = new Counter({
    name: 'cdp_hogflow_matcher_bytecode_error',
    help: 'A wait_until_condition or conversion-goal filter threw during evaluation. Filter is treated as non-matching, so the workflow falls through to its timeout branch.',
})

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
    buckets: [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5],
})

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
    private cyclotronPool: Pool

    constructor(config: TConfig, deps: CdpConsumerBaseDeps) {
        super(config, deps)
        // A waker only needs events that arrive after a job parks, never history, so start at the
        // head: auto.offset.reset=latest makes a fresh consumer group begin at the tip instead of
        // replaying the clickhouse_events_json backlog (unconsumable at prod volume).
        this.kafkaConsumer = createKafkaConsumer(
            {
                groupId: 'cdp-hogflow-subscription-matcher-consumer',
                topic: KAFKA_EVENTS_JSON,
            },
            { ['auto.offset.reset' as keyof RdKafkaConsumerConfig]: 'latest' as never }
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

    public async processBatch(invocationGlobals: HogFunctionInvocationGlobals[]): Promise<void> {
        if (!invocationGlobals.length) {
            return
        }
        try {
            await this.wakeMatchingWorkflows(invocationGlobals)
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
    private async wakeMatchingWorkflows(invocationGlobals: HogFunctionInvocationGlobals[]): Promise<void> {
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
                if (hasWaitUntilOrConversion(flow)) {
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
            Object.keys(hogflows)
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
            for (const globals of candidateGlobals) {
                const filterGlobals = filterGlobalsFor(globals)
                if (!stepMatched && action?.type === 'wait_until_condition') {
                    if (await this.evaluateWaitUntilCondition(action, filterGlobals, hogflow.id)) {
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
            if (stepMatched || conversionMatched) {
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

    private async evaluateWaitUntilCondition(
        action: Extract<HogFlowAction, { type: 'wait_until_condition' }>,
        filterGlobals: FilterGlobals,
        hogflowId: string
    ): Promise<boolean> {
        // `events` and the property-based `condition` are OR'd: a step can wait on either,
        // and either matching wakes the job. The condition is evaluated on every incoming
        // event, which is what makes property-based waits event-driven rather than polled.
        const context = { hogFlowId: hogflowId, actionId: action.id }
        for (const eventConfig of action.config.events ?? []) {
            if (!hasEventOrActionTarget(eventConfig)) {
                continue
            }
            if (await runBytecode(eventConfig.filters?.bytecode, filterGlobals, context)) {
                return true
            }
        }
        // An empty condition compiles to always-true bytecode, which would wake the job on the next
        // event of any kind. Only evaluate the condition when it has a real compiled filter;
        // otherwise the wait relies on its `events` / the step timeout.
        if (!isEvaluableCondition(action.config.condition)) {
            return false
        }
        return runBytecode(action.config.condition?.filters?.bytecode, filterGlobals, context)
    }

    private async evaluateConversionEvents(hogflow: HogFlow, filterGlobals: FilterGlobals): Promise<boolean> {
        const conversionEvents = hogflow.conversion?.events ?? []
        const context = { hogFlowId: hogflow.id }
        for (const eventConfig of conversionEvents) {
            if (!hasEventOrActionTarget(eventConfig)) {
                continue
            }
            if (await runBytecode(eventConfig.filters?.bytecode, filterGlobals, context)) {
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
        functionIds: string[]
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
        const stopTimer = histogramHogflowMatcherFindParkedJobs.startTimer()
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

    public override async start(): Promise<void> {
        await super.start()
        await this.kafkaConsumer.connect(async (messages) => {
            return await instrumentFn('cdpHogflowSubscriptionMatcher.handleEachBatch', async () => {
                const invocationGlobals = await this._parseKafkaBatch(messages)
                // Surface failures to the kafka consumer so the offset doesn't advance past a
                // batch we couldn't match. The pod will crash and replay; the SELECT is read-only
                // and the UPDATE (with `status = 'available'` guards) is idempotent, so replay is safe.
                return { backgroundTask: this.processBatch(invocationGlobals) }
            })
        })
    }

    public override async stop(): Promise<void> {
        logger.info('💤', `Stopping ${this.name}...`)
        await this.kafkaConsumer.disconnect()
        await this.cyclotronPool.end()
        await super.stop()
        logger.info('💤', `${this.name} stopped!`)
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
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

// An "events to wait for" / conversion entry that targets neither events nor actions compiles to
// always-true bytecode (the UI can leave an empty entry behind when the last event is removed), so
// it would match every incoming event. Action-based entries (events empty, actions set) are real
// and must be kept. Shared by the wait_until_condition and conversion evaluators so the rule lives
// in one place.
function hasEventOrActionTarget(eventConfig: { filters?: { events?: unknown[]; actions?: unknown[] } }): boolean {
    return Boolean(eventConfig.filters?.events?.length || eventConfig.filters?.actions?.length)
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

// Logged as separate fields on a bytecode error so it's filterable by flow/action.
// actionId is absent for a conversion goal (not an action).
type BytecodeContext = { hogFlowId: string; actionId?: string }

// Evaluates a compiled filter against the event. HogFlowSerializer compiles bytecode for
// every events[].filters at save time, so missing/empty bytecode means a malformed row:
// we fail closed (return false) rather than falling back to event-name-only matching, which
// would silently bypass property filters.
async function runBytecode(
    bytecode: unknown,
    filterGlobals: FilterGlobals,
    context: BytecodeContext
): Promise<boolean> {
    if (!Array.isArray(bytecode) || bytecode.length === 0) {
        return false
    }
    try {
        const result = await execHog(bytecode, { globals: filterGlobals })
        return result.execResult?.result === true
    } catch (err) {
        // A broken filter silently never matches and the workflow falls through to its
        // timeout branch, which is usually the wrong outcome. Surface loudly so we notice.
        logger.error('🔴', 'Bytecode evaluation error', { ...context, err })
        captureException(err, { extra: { ...context } })
        counterHogflowMatcherBytecodeError.inc()
        return false
    }
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
