import { Message } from 'node-rdkafka'
import { Pool } from 'pg'
import { Counter, Histogram } from 'prom-client'

import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'

import { KAFKA_EVENTS_JSON } from '../../config/kafka-topics'
import { KafkaConsumerInterface, createKafkaConsumer } from '../../kafka/consumer'
import { HogFlow, HogFlowAction } from '../../schema/hogflow'
import { HealthCheckResult, PluginsServerConfig, RawClickHouseEvent } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { HogFlowInvocationContext, HogFunctionInvocationGlobals } from '../types'
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
    actionId: string | null
    distinctId: string | null
    personId: string | null
}

type WakeRequest = {
    id: string
    stepMatched: boolean
    conversionMatched: boolean
    // Name and UUID of the event that matched, so the executor's resume log can surface the
    // name and the logs view can link to the exact event.
    eventName?: string
    eventUuid?: string
}

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
        this.kafkaConsumer = createKafkaConsumer({
            groupId: 'cdp-hogflow-subscription-matcher-consumer',
            topic: KAFKA_EVENTS_JSON,
        })

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
        await this.wakeMatchingWorkflows(invocationGlobals)
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

        const jobsToWake: WakeRequest[] = []
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
            let conversionMatched = false
            for (const globals of candidateGlobals) {
                const filterGlobals = filterGlobalsFor(globals)
                if (!stepMatched && action?.type === 'wait_until_condition') {
                    if (await this.evaluateWaitUntilCondition(action, filterGlobals)) {
                        stepMatched = true
                        stepMatchedEventName = globals.event.event
                        stepMatchedEventUuid = globals.event.uuid
                    }
                }
                if (!conversionMatched) {
                    conversionMatched = await this.evaluateConversionEvents(hogflow, filterGlobals)
                }
                if (stepMatched && conversionMatched) {
                    break
                }
            }

            if (stepMatched || conversionMatched) {
                jobsToWake.push({
                    id: candidate.id,
                    stepMatched,
                    conversionMatched,
                    eventName: stepMatchedEventName,
                    eventUuid: stepMatchedEventUuid,
                })
            }
        }

        if (jobsToWake.length === 0) {
            return
        }

        const woken = await this.wakeJobs(jobsToWake)
        counterHogflowMatcherJobsWoken.inc(woken)
        logger.info('⚡', 'Woke waiting workflows from event match', {
            evaluated: candidates.length,
            matched: jobsToWake.length,
            woken,
        })
    }

    private async evaluateWaitUntilCondition(
        action: Extract<HogFlowAction, { type: 'wait_until_condition' }>,
        filterGlobals: FilterGlobals
    ): Promise<boolean> {
        // `events` and the property-based `condition` are OR'd: a step can wait on either,
        // and either matching wakes the job. The condition is evaluated on every incoming
        // event, which is what makes property-based waits event-driven rather than polled.
        for (const eventConfig of action.config.events ?? []) {
            if (await runBytecode(eventConfig.filters?.bytecode, filterGlobals, action.id)) {
                return true
            }
        }
        return runBytecode(action.config.condition?.filters?.bytecode, filterGlobals, action.id)
    }

    private async evaluateConversionEvents(hogflow: HogFlow, filterGlobals: FilterGlobals): Promise<boolean> {
        const conversionEvents = hogflow.conversion?.events ?? []
        const contextId = `${hogflow.id}/conversion`
        for (const eventConfig of conversionEvents) {
            if (await runBytecode(eventConfig.filters?.bytecode, filterGlobals, contextId)) {
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
        const stopTimer = histogramHogflowMatcherFindParkedJobs.startTimer()
        let result
        try {
            result = await this.cyclotronPool.query(
                `SELECT id, team_id, function_id, action_id, distinct_id, person_id
             FROM cyclotron_jobs
             WHERE status = 'available'
               AND queue_name = 'hogflow'
               AND scheduled > NOW()
               AND function_id = ANY($5::uuid[])
               AND (team_id, distinct_id) IN (SELECT * FROM unnest($1::int[], $2::text[]))
             UNION
             SELECT id, team_id, function_id, action_id, distinct_id, person_id
             FROM cyclotron_jobs
             WHERE status = 'available'
               AND queue_name = 'hogflow'
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
            actionId: row.action_id,
            distinctId: row.distinct_id,
            personId: row.person_id,
        }))
    }

    private async wakeJobs(requests: WakeRequest[]): Promise<number> {
        if (requests.length === 0) {
            return 0
        }

        const ids = requests.map((r) => r.id)
        // The state read-modify-write must be atomic: two matcher instances waking the
        // same job (one stepMatched, one conversionMatched) would otherwise both read the
        // original state and the later UPDATE would drop the earlier flag. SELECT ... FOR
        // UPDATE inside a transaction serializes them — the second waker blocks, then reads
        // our committed state and merges its flag on top. ORDER BY id keeps lock acquisition
        // order consistent across instances so concurrent batches can't deadlock.
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

            const requestById = new Map(requests.map((r) => [r.id, r]))
            const updates: { id: string; state: Buffer }[] = []
            for (const row of stateRows.rows) {
                if (!row.state) {
                    continue
                }
                const req = requestById.get(row.id)
                if (!req) {
                    continue
                }
                const updated = applyWakeFlags(row.state, req)
                if (updated) {
                    updates.push({ id: row.id, state: updated })
                }
            }

            if (updates.length === 0) {
                await client.query('COMMIT')
                return 0
            }

            const result = await client.query(
                `UPDATE cyclotron_jobs cj
                 SET scheduled = NOW(), state = u.state
                 FROM (
                     SELECT unnest($1::uuid[]) AS id, unnest($2::bytea[]) AS state
                 ) u
                 WHERE cj.id = u.id AND cj.status = 'available'`,
                [updates.map((u) => u.id), updates.map((u) => u.state)]
            )
            await client.query('COMMIT')
            return result.rowCount ?? 0
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
    // Parallel arrays of (teamId, id) pairs, zipped row-wise in the lookup query so a
    // job only matches when BOTH its team and its id came from the same event. Sending
    // deduped teamId[] + id[] separately would let the query's ANY/ANY form match a job
    // whose team and distinct_id came from two different events (cross-team false positive).
    distinctTeamIds: number[]
    distinctIds: string[]
    personTeamIds: number[]
    personIds: string[]
    byDistinctId: Map<string, HogFunctionInvocationGlobals[]>
    byPersonId: Map<string, HogFunctionInvocationGlobals[]>
}

// Skip teams whose hogflows have no wait_until_condition step and no event-based
// conversion goal — nothing for the matcher to evaluate against.
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
            // First time we see this (team, distinct_id) pair, add it to the lookup arrays.
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

// Evaluates a compiled filter against the event. HogFlowSerializer compiles bytecode for
// every events[].filters at save time, so missing/empty bytecode means a malformed row:
// we fail closed (return false) rather than falling back to event-name-only matching, which
// would silently bypass property filters.
async function runBytecode(bytecode: unknown, filterGlobals: FilterGlobals, contextId: string): Promise<boolean> {
    if (!Array.isArray(bytecode) || bytecode.length === 0) {
        return false
    }
    try {
        const result = await execHog(bytecode, { globals: filterGlobals })
        return result.execResult?.result === true
    } catch (err) {
        // A broken filter silently never matches and the workflow falls through to its
        // timeout branch, which is usually the wrong outcome. Surface loudly so we notice.
        logger.error('🔴', 'Bytecode evaluation error', { contextId, err })
        captureException(err, { extra: { contextId } })
        counterHogflowMatcherBytecodeError.inc()
        return false
    }
}

function applyWakeFlags(stateBuffer: Buffer, req: WakeRequest): Buffer | null {
    try {
        const parsed = parseJSON(stateBuffer.toString('utf-8'))
        const updatedState: HogFlowInvocationContext = { ...parsed.state }

        let applied = false
        if (req.stepMatched) {
            if (updatedState.currentAction) {
                updatedState.currentAction = {
                    ...updatedState.currentAction,
                    eventMatched: true,
                    eventMatchedEvent: req.eventName,
                    eventMatchedEventUuid: req.eventUuid,
                }
                applied = true
            } else {
                // A parked wait_until_condition job should always carry its current action.
                // Without it we cannot tag the wake as an event match - skip the flag and
                // continue, since conversionMatched is independent of currentAction and may
                // still apply.
                logger.warn('Skipping eventMatched: no currentAction in state', { jobId: req.id })
            }
        }
        if (req.conversionMatched) {
            updatedState.conversionMatched = true
            applied = true
        }
        if (!applied) {
            // No flag set - waking the job without one would misclassify as a timeout wake.
            return null
        }
        parsed.state = updatedState
        return Buffer.from(JSON.stringify(parsed))
    } catch (err) {
        logger.warn('Failed to parse state during wake', { jobId: req.id, err })
        return null
    }
}
