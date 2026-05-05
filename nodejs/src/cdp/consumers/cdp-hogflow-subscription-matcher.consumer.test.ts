import { HogFlow } from '../../schema/hogflow'
import { parseJSON } from '../../utils/json-parse'
import { HogFunctionInvocationGlobals } from '../types'
import { CdpHogflowSubscriptionMatcherConsumer } from './cdp-hogflow-subscription-matcher.consumer'

jest.mock('./cdp-base.consumer', () => {
    return {
        CdpConsumerBase: class {
            constructor(_config: any, _deps: any) {}
        },
    }
})

jest.mock('../../kafka/consumer', () => ({
    KafkaConsumer: jest.fn().mockImplementation(() => ({})),
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

const makeHogFlow = (overrides: Partial<HogFlow> & { id: string }): HogFlow => {
    const { id, team_id, ...rest } = overrides
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
            {
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
            },
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
        ;(this as any).cyclotronPool = {
            query: jest.fn((sql: string, params: any[]) => {
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
            }),
        }
        // Stub hogFlowManager
        ;(this as any).hogFlowManager = {
            getHogFlows: jest.fn(),
        }
    }

    public setHogFlows(map: Record<string, HogFlow>): void {
        ;(this as any).hogFlowManager.getHogFlows.mockResolvedValue(map)
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
            await matcher.runWake([
                makeGlobals({}),
                makeGlobals({
                    event: { ...makeGlobals({}).event, distinct_id: 'user-2', uuid: 'e2' },
                    person: { id: 'person-uuid-2', properties: {}, name: '', url: '' },
                }),
            ])
            const lookup = matcher.calls.find((c) => c.sql.includes('SELECT id, team_id, function_id'))!
            expect(lookup).toBeDefined()
            expect(lookup.params[0]).toEqual([1])
            expect(lookup.params[1].sort()).toEqual(['user-1', 'user-2'])
            expect(lookup.params[2].sort()).toEqual(['person-uuid-1', 'person-uuid-2'])
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
            expect(update).toBeDefined()
            expect(update!.params[0]).toEqual(['job-1'])
            const newState = parseJSON(update!.params[1][0].toString('utf-8')) as any
            expect(newState.state.currentAction.eventMatched).toBe(true)
            expect(newState.state.conversionMatched).toBeUndefined()
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
            expect(update).toBeDefined()
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
            matcher.findRows = []
            matcher.setHogFlows({})

            await matcher.runWake([makeGlobals({})])

            // Lookup query is made; no UPDATE follows
            expect(matcher.calls.find((c) => c.sql.includes('SELECT id, team_id, function_id'))).toBeDefined()
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
            expect(update).toBeDefined()
            expect(update!.params[0]).toEqual(['job-match'])
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
            expect(stateLoad).toBeDefined()
            // wakeJobs is called with only the matching id; SELECT id, state pulls only that
            expect(stateLoad!.params[0]).toEqual(['job-match'])
        })
    })
})
