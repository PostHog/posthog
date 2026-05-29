import { HogFlow } from '../../schema/hogflow'
import { parseJSON } from '../../utils/json-parse'
import { HogFunctionInvocationGlobals } from '../types'
import { CdpHogflowSubscriptionMatcherConsumer } from './cdp-hogflow-subscription-matcher.consumer'

jest.mock('./cdp-base.consumer', () => {
    return {
        CdpConsumerBase: class {
            constructor() {}
            async start(): Promise<void> {}
        },
    }
})

jest.mock('../../kafka/consumer', () => ({
    createKafkaConsumer: jest.fn().mockReturnValue({}),
}))

jest.mock('pg', () => {
    const Pool = jest.fn()
    return { Pool }
})

type MockRow = {
    id: string
    team_id: number
    function_id: string
    action_id: string | null
    distinct_id: string | null
    person_id: string | null
    state?: Buffer | null
}

const eventBytecode = (eventName: string): any[] => ['_H', 1, 32, eventName, 32, 'event', 1, 1, 11]

const makeHogFlow = (overrides: Partial<HogFlow> & { id: string; waitUntil?: boolean }): HogFlow => {
    const { id, team_id, waitUntil = true, ...rest } = overrides
    const waitAction = {
        id: 'wait_node',
        name: 'Wait',
        type: 'wait_until_condition',
        config: {
            events: [
                {
                    filters: {
                        bytecode: eventBytecode('wuc_subscribed'),
                        events: [{ id: 'wuc_subscribed', name: 'wuc_subscribed', type: 'events', order: 0 }],
                    },
                },
            ],
            condition: { filters: null },
            max_wait_duration: '5m',
        },
    }
    return {
        id,
        team_id: team_id ?? 1,
        version: 1,
        status: 'active',
        actions: [
            {
                id: 'trigger_node',
                name: 'Trigger',
                type: 'trigger',
                config: { type: 'event', filters: {} },
            },
            ...(waitUntil ? [waitAction] : []),
            { id: 'exit_node', name: 'Exit', type: 'exit', config: {} },
        ],
        edges: [],
        conversion: null,
        ...rest,
    } as unknown as HogFlow
}

const makeGlobals = (overrides: Partial<HogFunctionInvocationGlobals>): HogFunctionInvocationGlobals =>
    ({
        project: { id: 1, name: 'Test', url: '' },
        event: {
            uuid: 'event-uuid',
            event: 'wuc_subscribed',
            distinct_id: 'user-1',
            properties: {},
            elements_chain: '',
            timestamp: new Date().toISOString(),
            url: '',
        },
        person: { id: 'person-uuid-1', properties: {}, name: 'User 1', url: '' },
        ...overrides,
    }) as HogFunctionInvocationGlobals

interface QueryCall {
    sql: string
    params: any[]
}

class MatcherUnderTest extends CdpHogflowSubscriptionMatcherConsumer {
    public calls: QueryCall[] = []
    public findRows: MockRow[] = []
    public wakeRows: MockRow[] = []
    public updateRowCount = 0

    constructor() {
        super({ CYCLOTRON_NODE_DATABASE_URL: '' } as any, {} as any)
        // Wire a fake pool that dispatches queries to predefined fixtures.
        const dispatch = (sql: string, params: any[]): Promise<{ rows: any[]; rowCount: number }> => {
            if (sql === 'BEGIN' || sql === 'COMMIT' || sql === 'ROLLBACK') {
                return Promise.resolve({ rows: [], rowCount: 0 })
            }
            this.calls.push({ sql, params })
            if (sql.includes('SELECT id, team_id, function_id')) {
                return Promise.resolve({ rows: this.findRows, rowCount: this.findRows.length })
            }
            if (sql.includes('SELECT id, state FROM cyclotron_jobs')) {
                return Promise.resolve({ rows: this.wakeRows, rowCount: this.wakeRows.length })
            }
            if (sql.startsWith('UPDATE cyclotron_jobs')) {
                return Promise.resolve({ rows: [], rowCount: this.updateRowCount })
            }
            return Promise.resolve({ rows: [], rowCount: 0 })
        }
        ;(this as any).cyclotronPool = {
            query: jest.fn((sql: string, params: any[]) => dispatch(sql, params)),
            connect: jest.fn(() =>
                Promise.resolve({
                    query: jest.fn((sql: string, params: any[]) => dispatch(sql, params)),
                    release: jest.fn(),
                })
            ),
        }
        // Stub hogFlowManager
        ;(this as any).hogFlowManager = {
            getHogFlowsForTeams: jest.fn().mockResolvedValue({}),
        }
    }

    public setHogFlows(map: Record<string, HogFlow>): void {
        const byTeam: Record<number, HogFlow[]> = {}
        for (const flow of Object.values(map)) {
            byTeam[flow.team_id] = byTeam[flow.team_id] ?? []
            byTeam[flow.team_id].push(flow)
        }
        ;(this as any).hogFlowManager.getHogFlowsForTeams.mockResolvedValue(byTeam)
    }

    public async runWake(invocationGlobals: HogFunctionInvocationGlobals[]): Promise<void> {
        await (this as any).wakeMatchingWorkflows(invocationGlobals)
    }
}

const stateBuffer = (state: any): Buffer => Buffer.from(JSON.stringify({ state }))

describe('CdpHogflowSubscriptionMatcherConsumer', () => {
    let matcher: MatcherUnderTest

    beforeEach(() => {
        matcher = new MatcherUnderTest()
    })

    describe('wakeMatchingWorkflows', () => {
        it('is a no-op when no events have person_id', async () => {
            await matcher.runWake([
                makeGlobals({ person: undefined as any, event: { ...makeGlobals({}).event, distinct_id: '' } }),
            ])
            expect(matcher.calls).toHaveLength(0)
        })

        it('passes both distinct_ids and person_ids to the lookup query', async () => {
            // Need a qualifying hogflow on the team or the team-level early-out skips findParkedJobs.
            matcher.setHogFlows({ 'flow-1': makeHogFlow({ id: 'flow-1' }) })
            await matcher.runWake([
                makeGlobals({}),
                makeGlobals({
                    event: { ...makeGlobals({}).event, distinct_id: 'user-2', uuid: 'e2' },
                    person: { id: 'person-uuid-2', properties: {}, name: '', url: '' },
                }),
            ])
            const lookup = matcher.calls.find((c) => c.sql.includes('SELECT id, team_id, function_id'))!
            expect(lookup).not.toBeUndefined()
            // Params are correlated (team, id) pairs: distinctTeamIds/distinctIds zip row-wise,
            // and personTeamIds/personIds zip row-wise. Both events are team 1.
            expect(lookup.params[0]).toEqual([1, 1]) // distinctTeamIds
            expect(lookup.params[1]).toEqual(['user-1', 'user-2']) // distinctIds
            expect(lookup.params[2]).toEqual([1, 1]) // personTeamIds
            expect(lookup.params[3]).toEqual(['person-uuid-1', 'person-uuid-2']) // personIds
            expect(lookup.params[4]).toEqual(['flow-1']) // functionIds
        })

        it('correlates team_id with distinct_id so a cross-team pairing is never queried or woken', async () => {
            // Bug scenario: event A is (team 1, alice), event B is (team 2, bob). A naive
            // `team_id = ANY([1,2]) AND distinct_id = ANY([alice,bob])` query would also match
            // a parked job at (team 1, bob) — a team/id combination that no event in the batch
            // actually carried. The lookup must only ever ask for (team 1, alice) and (team 2, bob).
            matcher.setHogFlows({
                'flow-1': makeHogFlow({ id: 'flow-1', team_id: 1 }),
                'flow-2': makeHogFlow({ id: 'flow-2', team_id: 2 }),
            })

            // Pretend the DB still returned the cross-team false positive (team 1, bob). The
            // in-memory guard must reject it because no batch event was for (team 1, bob).
            matcher.findRows = [
                {
                    id: 'job-cross',
                    team_id: 1,
                    function_id: 'flow-1',
                    action_id: 'wait_node',
                    distinct_id: 'bob',
                    person_id: null,
                },
            ]
            matcher.wakeRows = [
                { ...matcher.findRows[0], state: stateBuffer({ currentAction: { id: 'wait_node' } }) },
            ]
            matcher.updateRowCount = 1

            await matcher.runWake([
                makeGlobals({ project: { id: 1, name: 'T1', url: '' }, event: { ...makeGlobals({}).event, distinct_id: 'alice', uuid: 'e1' }, person: undefined }),
                makeGlobals({ project: { id: 2, name: 'T2', url: '' }, event: { ...makeGlobals({}).event, distinct_id: 'bob', uuid: 'e2' }, person: undefined }),
            ])

            // The correlated lookup params zip (team, distinct_id) row-wise: {(1,alice),(2,bob)}.
            // (1,bob) must not appear — that's the cross-team combination that doesn't exist.
            const lookup = matcher.calls.find((c) => c.sql.includes('SELECT id, team_id, function_id'))!
            expect(lookup).not.toBeUndefined()
            const pairs = lookup.params[0].map((teamId: number, i: number) => `${teamId}:${lookup.params[1][i]}`)
            expect(pairs).toEqual(['1:alice', '2:bob'])
            expect(pairs).not.toContain('1:bob')
            // And the query is genuinely correlated (tuple form), not independent ANY/ANY.
            expect(lookup.sql).toContain('(team_id, distinct_id) IN (SELECT * FROM unnest($1::int[], $2::text[]))')

            // The stray cross-team candidate is filtered in-memory → no job is woken.
            const update = matcher.calls.find((c) => c.sql.startsWith('UPDATE cyclotron_jobs'))
            expect(update).toBeUndefined()
        })

        it('scopes the lookup to qualifying flows, excluding non-wait flows on the same team', async () => {
            matcher.setHogFlows({
                'flow-1': makeHogFlow({ id: 'flow-1' }),
                'flow-2': makeHogFlow({ id: 'flow-2', waitUntil: false }),
            })
            await matcher.runWake([makeGlobals({})])
            const lookup = matcher.calls.find((c) => c.sql.includes('SELECT id, team_id, function_id'))!
            expect(lookup).not.toBeUndefined()
            expect(lookup.params[4]).toEqual(['flow-1'])
        })

        it('skips cyclotron entirely when no team in the batch has a wait_until_condition or conversion goal', async () => {
            // Default: no hogflows configured → team has nothing the matcher could wake.
            // The cyclotron lookup must NOT fire.
            await matcher.runWake([makeGlobals({})])
            expect(matcher.calls.find((c) => c.sql.includes('SELECT id, team_id, function_id'))).toBeUndefined()
        })

        it('wakes when the matching event is not the first event in the batch for a distinct_id', async () => {
            // Two events for the same user in one batch. The first does not match the
            // wait condition; the second does. The matcher must evaluate both, not just
            // the first one it indexed.
            matcher.findRows = [
                {
                    id: 'job-1',
                    team_id: 1,
                    function_id: 'flow-1',
                    action_id: 'wait_node',
                    distinct_id: 'user-1',
                    person_id: null,
                },
            ]
            matcher.wakeRows = [{ ...matcher.findRows[0], state: stateBuffer({ currentAction: { id: 'wait_node' } }) }]
            matcher.updateRowCount = 1
            matcher.setHogFlows({ 'flow-1': makeHogFlow({ id: 'flow-1' }) })

            await matcher.runWake([
                makeGlobals({ event: { ...makeGlobals({}).event, event: 'random_event', uuid: 'e1' } }),
                makeGlobals({ event: { ...makeGlobals({}).event, event: 'wuc_subscribed', uuid: 'e2' } }),
            ])

            const update = matcher.calls.find((c) => c.sql.startsWith('UPDATE cyclotron_jobs'))
            expect(update).not.toBeUndefined()
            expect(update!.params[0]).toEqual(['job-1'])
        })

        it('wakes a job matched by distinct_id (event-triggered scenario)', async () => {
            matcher.findRows = [
                {
                    id: 'job-1',
                    team_id: 1,
                    function_id: 'flow-1',
                    action_id: 'wait_node',
                    distinct_id: 'user-1',
                    person_id: null,
                },
            ]
            matcher.wakeRows = [{ ...matcher.findRows[0], state: stateBuffer({ currentAction: { id: 'wait_node' } }) }]
            matcher.updateRowCount = 1
            matcher.setHogFlows({ 'flow-1': makeHogFlow({ id: 'flow-1' }) })

            await matcher.runWake([makeGlobals({})])

            const update = matcher.calls.find((c) => c.sql.startsWith('UPDATE cyclotron_jobs'))
            expect(update).not.toBeUndefined()
            expect(update!.params[0]).toEqual(['job-1'])
            const newState = parseJSON(update!.params[1][0].toString('utf-8')) as any
            expect(newState.state.currentAction.eventMatched).toBe(true)
            expect(newState.state.conversionMatched).toBeUndefined()
        })

        it('does not wake when the wait step has events without bytecode (fail-closed)', async () => {
            // HogFlowSerializer compiles bytecode at save time; a row that reaches the
            // matcher without bytecode is malformed and must not fall back to event-name
            // matching, which would silently bypass property filters.
            matcher.findRows = [
                {
                    id: 'job-1',
                    team_id: 1,
                    function_id: 'flow-1',
                    action_id: 'wait_node',
                    distinct_id: 'user-1',
                    person_id: null,
                },
            ]
            matcher.wakeRows = [{ ...matcher.findRows[0], state: stateBuffer({ currentAction: { id: 'wait_node' } }) }]
            matcher.updateRowCount = 1
            const flow = makeHogFlow({ id: 'flow-1' })
            ;(flow.actions as any[])[1].config.events[0].filters.bytecode = []
            matcher.setHogFlows({ 'flow-1': flow })

            await matcher.runWake([makeGlobals({})])

            const update = matcher.calls.find((c) => c.sql.startsWith('UPDATE cyclotron_jobs'))
            expect(update).toBeUndefined()
        })

        it('skips waking a matched job whose state has no currentAction', async () => {
            matcher.findRows = [
                {
                    id: 'job-1',
                    team_id: 1,
                    function_id: 'flow-1',
                    action_id: 'wait_node',
                    distinct_id: 'user-1',
                    person_id: null,
                },
            ]
            // State is missing currentAction, so the matcher cannot tag the wake as an
            // event match. It must skip the job rather than misclassify it as a timeout.
            matcher.wakeRows = [{ ...matcher.findRows[0], state: stateBuffer({}) }]
            matcher.updateRowCount = 1
            matcher.setHogFlows({ 'flow-1': makeHogFlow({ id: 'flow-1' }) })

            await matcher.runWake([makeGlobals({})])

            const update = matcher.calls.find((c) => c.sql.startsWith('UPDATE cyclotron_jobs'))
            expect(update).toBeUndefined()
        })

        it('still wakes a job for a conversion match when stepMatched lacks currentAction', async () => {
            matcher.findRows = [
                {
                    id: 'job-1',
                    team_id: 1,
                    function_id: 'flow-1',
                    action_id: 'wait_node',
                    distinct_id: 'user-1',
                    person_id: null,
                },
            ]
            // State missing currentAction: we cannot tag eventMatched, but the same incoming
            // event also satisfies the workflow's conversion goal, which is independent of
            // currentAction - that wake must still happen.
            matcher.wakeRows = [{ ...matcher.findRows[0], state: stateBuffer({}) }]
            matcher.updateRowCount = 1
            matcher.setHogFlows({
                'flow-1': makeHogFlow({
                    id: 'flow-1',
                    conversion: {
                        window_minutes: null,
                        filters: {},
                        bytecode: [],
                        events: [
                            {
                                filters: {
                                    events: [{ id: 'wuc_subscribed' }],
                                    bytecode: eventBytecode('wuc_subscribed'),
                                },
                            },
                        ],
                    },
                } as any),
            })

            await matcher.runWake([makeGlobals({})])

            const update = matcher.calls.find((c) => c.sql.startsWith('UPDATE cyclotron_jobs'))
            expect(update).not.toBeUndefined()
            const newState = parseJSON(update!.params[1][0].toString('utf-8')) as any
            expect(newState.state.conversionMatched).toBe(true)
            // currentAction is missing in input state, so eventMatched must not have been set
            expect(newState.state.currentAction).toBeUndefined()
        })

        it('wakes a job matched by person_id (batch-triggered scenario, distinct_id mismatch)', async () => {
            matcher.findRows = [
                {
                    id: 'job-batch',
                    team_id: 1,
                    function_id: 'flow-1',
                    action_id: 'wait_node',
                    distinct_id: null,
                    person_id: 'person-uuid-1',
                },
            ]
            matcher.wakeRows = [
                {
                    ...matcher.findRows[0],
                    state: stateBuffer({ currentAction: { id: 'wait_node' }, personId: 'person-uuid-1' }),
                },
            ]
            matcher.updateRowCount = 1
            matcher.setHogFlows({ 'flow-1': makeHogFlow({ id: 'flow-1' }) })

            await matcher.runWake([
                makeGlobals({
                    event: { ...makeGlobals({}).event, distinct_id: 'fresh-distinct-id' },
                    person: { id: 'person-uuid-1', properties: {}, name: '', url: '' },
                }),
            ])

            const update = matcher.calls.find((c) => c.sql.startsWith('UPDATE cyclotron_jobs'))
            expect(update).not.toBeUndefined()
            expect(update!.params[0]).toEqual(['job-batch'])
        })

        it('sets conversionMatched on top-level state when workflow conversion event fires', async () => {
            const flow = makeHogFlow({
                id: 'flow-1',
                conversion: {
                    events: [
                        {
                            filters: {
                                bytecode: eventBytecode('wuc_cancelled'),
                                events: [{ id: 'wuc_cancelled', name: 'wuc_cancelled', type: 'events', order: 0 }],
                            },
                        },
                    ],
                } as any,
            } as any)
            matcher.findRows = [
                {
                    id: 'job-c',
                    team_id: 1,
                    function_id: 'flow-1',
                    action_id: 'wait_node',
                    distinct_id: 'user-1',
                    person_id: null,
                },
            ]
            matcher.wakeRows = [{ ...matcher.findRows[0], state: stateBuffer({ currentAction: { id: 'wait_node' } }) }]
            matcher.updateRowCount = 1
            matcher.setHogFlows({ 'flow-1': flow })

            await matcher.runWake([makeGlobals({ event: { ...makeGlobals({}).event, event: 'wuc_cancelled' } })])

            const update = matcher.calls.find((c) => c.sql.startsWith('UPDATE cyclotron_jobs'))
            const newState = parseJSON(update!.params[1][0].toString('utf-8')) as any
            expect(newState.state.conversionMatched).toBe(true)
        })

        it('does not wake when neither step filter nor conversion matches', async () => {
            matcher.findRows = [
                {
                    id: 'job-1',
                    team_id: 1,
                    function_id: 'flow-1',
                    action_id: 'wait_node',
                    distinct_id: 'user-1',
                    person_id: null,
                },
            ]
            matcher.setHogFlows({ 'flow-1': makeHogFlow({ id: 'flow-1' }) })

            // Event name doesn't match wuc_subscribed (waiter event) nor any conversion
            await matcher.runWake([makeGlobals({ event: { ...makeGlobals({}).event, event: 'unrelated_event' } })])

            const update = matcher.calls.find((c) => c.sql.startsWith('UPDATE cyclotron_jobs'))
            expect(update).toBeUndefined()
        })

        it('skips candidates whose hogflow is not in cache', async () => {
            matcher.findRows = [
                {
                    id: 'job-1',
                    team_id: 1,
                    function_id: 'unknown-flow',
                    action_id: 'wait_node',
                    distinct_id: 'user-1',
                    person_id: null,
                },
            ]
            matcher.setHogFlows({})

            await matcher.runWake([makeGlobals({})])

            const update = matcher.calls.find((c) => c.sql.startsWith('UPDATE cyclotron_jobs'))
            expect(update).toBeUndefined()
        })

        it('skips wait step that is not a wait_until_condition (and no conversion match)', async () => {
            const flow = makeHogFlow({ id: 'flow-1' })
            // Replace the wait node with a delay
            ;(flow.actions as any[])[1] = { id: 'delay_node', name: 'Delay', type: 'delay', config: {} }
            matcher.findRows = [
                {
                    id: 'job-1',
                    team_id: 1,
                    function_id: 'flow-1',
                    action_id: 'delay_node',
                    distinct_id: 'user-1',
                    person_id: null,
                },
            ]
            matcher.setHogFlows({ 'flow-1': flow })

            await matcher.runWake([makeGlobals({})])

            const update = matcher.calls.find((c) => c.sql.startsWith('UPDATE cyclotron_jobs'))
            expect(update).toBeUndefined()
        })

        it('returns no candidates when lookup query returns empty', async () => {
            // Team has a qualifying hogflow, so the team-level early-out doesn't fire and we
            // do hit cyclotron — but the lookup itself returns no rows, so no UPDATE follows.
            matcher.findRows = []
            matcher.setHogFlows({ 'flow-1': makeHogFlow({ id: 'flow-1' }) })

            await matcher.runWake([makeGlobals({})])

            expect(matcher.calls.find((c) => c.sql.includes('SELECT id, team_id, function_id'))).not.toBeUndefined()
            expect(matcher.calls.find((c) => c.sql.startsWith('UPDATE cyclotron_jobs'))).toBeUndefined()
        })

        it('wakes only matching subset when multiple candidates returned', async () => {
            matcher.findRows = [
                {
                    id: 'job-match',
                    team_id: 1,
                    function_id: 'flow-1',
                    action_id: 'wait_node',
                    distinct_id: 'user-1',
                    person_id: null,
                },
                {
                    id: 'job-nomatch',
                    team_id: 1,
                    function_id: 'flow-no-match',
                    action_id: 'wait_node',
                    distinct_id: 'user-1',
                    person_id: null,
                },
            ]
            matcher.wakeRows = [
                {
                    id: 'job-match',
                    team_id: 1,
                    function_id: 'flow-1',
                    action_id: 'wait_node',
                    distinct_id: 'user-1',
                    person_id: null,
                    state: stateBuffer({ currentAction: { id: 'wait_node' } }),
                },
            ]
            matcher.updateRowCount = 1

            // flow-no-match waits on a different event name
            const noMatchFlow = makeHogFlow({ id: 'flow-no-match' })
            ;(noMatchFlow.actions as any[])[1].config.events[0].filters.bytecode = eventBytecode('something_else')
            ;(noMatchFlow.actions as any[])[1].config.events[0].filters.events[0].id = 'something_else'
            ;(noMatchFlow.actions as any[])[1].config.events[0].filters.events[0].name = 'something_else'

            matcher.setHogFlows({
                'flow-1': makeHogFlow({ id: 'flow-1' }),
                'flow-no-match': noMatchFlow,
            })

            await matcher.runWake([makeGlobals({})])

            const update = matcher.calls.find((c) => c.sql.startsWith('UPDATE cyclotron_jobs'))
            expect(update).not.toBeUndefined()
            expect(update!.params[0]).toEqual(['job-match'])
        })

        it('propagates processBatch failures through backgroundTask (no swallow)', async () => {
            // Kafka offsets must not advance past a batch we couldn't match. Otherwise a
            // transient cyclotron failure silently misses wakeups. The consumer-v2 fatalError
            // gate then crashes the pod and replays — the SELECT is read-only and the UPDATE
            // is guarded by `status = 'available'`, so replay is idempotent.
            const failure = new Error('connection refused')
            // Need a qualifying hogflow so the team-level early-out doesn't skip the cyclotron
            // call we want to see fail.
            matcher.setHogFlows({ 'flow-1': makeHogFlow({ id: 'flow-1' }) })
            ;(matcher as any).cyclotronPool.query = jest.fn().mockRejectedValue(failure)
            ;(matcher as any)._parseKafkaBatch = jest.fn().mockResolvedValue([makeGlobals({})])

            let capturedEachBatch: ((messages: any[]) => Promise<any>) | undefined
            ;(matcher as any).kafkaConsumer = {
                connect: jest.fn((cb: (messages: any[]) => Promise<any>) => {
                    capturedEachBatch = cb
                    return Promise.resolve()
                }),
            }

            await matcher.start()
            const result = await capturedEachBatch!([{ value: Buffer.from('{}') }])

            await expect(result.backgroundTask).rejects.toBe(failure)
        })

        it('does not load state for non-matching candidates (projection-only lookup)', async () => {
            // Two candidates returned, only one matches the wait filter.
            matcher.findRows = [
                {
                    id: 'job-match',
                    team_id: 1,
                    function_id: 'flow-1',
                    action_id: 'wait_node',
                    distinct_id: 'user-1',
                    person_id: null,
                },
                {
                    id: 'job-nomatch',
                    team_id: 1,
                    function_id: 'flow-no-match',
                    action_id: 'wait_node',
                    distinct_id: 'user-1',
                    person_id: null,
                },
            ]
            matcher.wakeRows = [
                {
                    id: 'job-match',
                    team_id: 1,
                    function_id: 'flow-1',
                    action_id: 'wait_node',
                    distinct_id: 'user-1',
                    person_id: null,
                    state: stateBuffer({ currentAction: { id: 'wait_node' } }),
                },
            ]
            matcher.updateRowCount = 1

            const noMatchFlow = makeHogFlow({ id: 'flow-no-match' })
            ;(noMatchFlow.actions as any[])[1].config.events[0].filters.bytecode = eventBytecode('other')

            matcher.setHogFlows({
                'flow-1': makeHogFlow({ id: 'flow-1' }),
                'flow-no-match': noMatchFlow,
            })

            await matcher.runWake([makeGlobals({})])

            const stateLoad = matcher.calls.find((c) => c.sql.includes('SELECT id, state FROM cyclotron_jobs'))
            expect(stateLoad).not.toBeUndefined()
            // wakeJobs is called with only the matching id; SELECT id, state pulls only that
            expect(stateLoad!.params[0]).toEqual(['job-match'])
        })
    })
})
