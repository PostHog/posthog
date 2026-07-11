import { HogFlow } from '~/cdp/schema/hogflow'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import * as posthogUtils from '~/common/utils/posthog'

import { HogFunctionInvocationGlobals } from '../types'
import * as hogExec from '../utils/hog-exec'
import { CdpHogflowSubscriptionMatcherConsumer } from './cdp-hogflow-subscription-matcher.consumer'

jest.mock('./cdp-base.consumer', () => {
    return {
        CdpConsumerBase: class {
            constructor() {}
            async start(): Promise<void> {}
        },
    }
})

jest.mock('~/common/kafka/consumer', () => ({
    // Fresh stub per call: the matcher now constructs three consumers (events, person, internal
    // events), and start()/stop()/isHealthy() touch all of them.
    createKafkaConsumer: jest.fn(() => ({
        connect: jest.fn().mockResolvedValue(undefined),
        disconnect: jest.fn().mockResolvedValue(undefined),
        isHealthy: jest.fn(),
    })),
}))

jest.mock('pg', () => {
    const Pool = jest.fn()
    return { Pool }
})

type MockRow = {
    id: string
    team_id: number
    function_id: string
    parent_run_id?: string | null
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

const makeAgentTaskFlow = (id: string, team_id = 1): HogFlow =>
    ({
        id,
        team_id,
        version: 1,
        status: 'active',
        actions: [
            { id: 'trigger_node', name: 'Trigger', type: 'trigger', config: { type: 'event', filters: {} } },
            { id: 'agent_node', name: 'Agent', type: 'agent_task', config: { prompt: 'go', max_wait_duration: '2h' } },
            { id: 'exit_node', name: 'Exit', type: 'exit', config: {} },
        ],
        edges: [],
        conversion: null,
    }) as unknown as HogFlow

const makeTaskCompletionEvent = (
    taskRunId: string,
    status: string,
    output: unknown,
    distinctId = 'user-1'
): HogFunctionInvocationGlobals =>
    ({
        project: { id: 1, name: 'Test', url: '' },
        event: {
            uuid: 'task-event-uuid',
            event: '$task_run_completed',
            distinct_id: distinctId,
            properties: { task_run_id: taskRunId, status, output },
            elements_chain: '',
            timestamp: new Date().toISOString(),
            url: '',
        },
        person: { id: 'person-uuid-1', properties: {}, name: 'User 1', url: '' },
    }) as HogFunctionInvocationGlobals

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
        // Non-empty URL satisfies the constructor's fail-fast guard; the real Pool (mocked
        // via jest.mock('pg')) is immediately replaced below with a fixture-dispatching fake.
        super({ CYCLOTRON_NODE_DATABASE_URL: 'postgres://test' } as any, {} as any)
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
            getHogFlowsForTeam: jest.fn().mockResolvedValue([]),
        }
        // CdpConsumerBase is mocked out in these tests, so the monitoring service it normally
        // provides is absent. Stub it so the matcher can queue/flush the `conversion` app metric.
        ;(this as any).hogFunctionMonitoringService = {
            queueAppMetric: jest.fn(),
            flush: jest.fn().mockResolvedValue(undefined),
        }
        // Likewise stub the captured-events service used to emit $workflows_conversion events.
        ;(this as any).invocationResultsService = {
            capturedEventsService: {
                queueEvent: jest.fn().mockResolvedValue(undefined),
                flush: jest.fn().mockResolvedValue(undefined),
            },
        }
    }

    public get queueAppMetricMock(): jest.Mock {
        return (this as any).hogFunctionMonitoringService.queueAppMetric
    }

    public get queueConversionEventMock(): jest.Mock {
        return (this as any).invocationResultsService.capturedEventsService.queueEvent
    }

    public setHogFlows(map: Record<string, HogFlow>): void {
        const byTeam: Record<number, HogFlow[]> = {}
        for (const flow of Object.values(map)) {
            byTeam[flow.team_id] = byTeam[flow.team_id] ?? []
            byTeam[flow.team_id].push(flow)
        }
        ;(this as any).hogFlowManager.getHogFlowsForTeams.mockResolvedValue(byTeam)
        ;(this as any).hogFlowManager.getHogFlowsForTeam.mockImplementation((teamId: number) =>
            Promise.resolve(byTeam[teamId] ?? [])
        )
    }

    public async runWake(
        invocationGlobals: HogFunctionInvocationGlobals[],
        source: 'events' | 'person' | 'internal_events' = 'events'
    ): Promise<void> {
        await (this as any).wakeMatchingWorkflows(invocationGlobals, source)
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

        it('does not constrain the lookup by queue_name so waits parked on any queue are found', async () => {
            // A wait that follows an email step parks on the email queue, not hogflow. The lookup
            // must not filter queue_name or it would silently miss those parked jobs; function_id
            // already scopes the results to hogflow jobs.
            matcher.setHogFlows({ 'flow-1': makeHogFlow({ id: 'flow-1' }) })
            await matcher.runWake([makeGlobals({})])
            const lookup = matcher.calls.find((c) => c.sql.includes('SELECT id, team_id, function_id'))!
            expect(lookup).not.toBeUndefined()
            expect(lookup.sql).not.toContain('queue_name')
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
            matcher.wakeRows = [{ ...matcher.findRows[0], state: stateBuffer({ currentAction: { id: 'wait_node' } }) }]
            matcher.updateRowCount = 1

            await matcher.runWake([
                makeGlobals({
                    project: { id: 1, name: 'T1', url: '' },
                    event: { ...makeGlobals({}).event, distinct_id: 'alice', uuid: 'e1' },
                    person: undefined,
                }),
                makeGlobals({
                    project: { id: 2, name: 'T2', url: '' },
                    event: { ...makeGlobals({}).event, distinct_id: 'bob', uuid: 'e2' },
                    person: undefined,
                }),
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

            await matcher.runWake([
                makeGlobals({ event: { ...makeGlobals({}).event, timestamp: '2026-01-30T21:00:00.000Z' } }),
            ])

            const update = matcher.calls.find((c) => c.sql.startsWith('UPDATE cyclotron_jobs'))
            expect(update).not.toBeUndefined()
            expect(update!.params[0]).toEqual(['job-1'])
            const newState = parseJSON(update!.params[1][0].toString('utf-8')) as any
            expect(newState.state.currentAction.eventMatched).toBe(true)
            expect(newState.state.currentAction.eventMatchedEvent).toBe('wuc_subscribed')
            expect(newState.state.currentAction.eventMatchedEventUuid).toBe('event-uuid')
            expect(newState.state.currentAction.eventMatchedEventTimestamp).toBe('2026-01-30T21:00:00.000Z')
            expect(newState.state.conversionMatched).toBeUndefined()
        })

        it('logs the hogflow id alongside the action id when wait-step bytecode evaluation throws', async () => {
            const errorSpy = jest.spyOn(logger, 'error').mockReturnValue(undefined as any)
            const execSpy = jest.spyOn(hogExec, 'execHog').mockRejectedValue(new Error('boom'))
            const captureSpy = jest.spyOn(posthogUtils, 'captureException').mockReturnValue(undefined as any)

            try {
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
                await matcher.runWake([makeGlobals({})])

                const errorCall = errorSpy.mock.calls.find((c) => c[1] === 'Bytecode evaluation error')
                expect(errorCall).toBeDefined()
                expect(errorCall![2]).toMatchObject({ hogFlowId: 'flow-1', actionId: 'wait_node' })
                expect(captureSpy).toHaveBeenCalledWith(expect.any(Error), {
                    extra: { hogFlowId: 'flow-1', actionId: 'wait_node' },
                })
            } finally {
                errorSpy.mockRestore()
                execSpy.mockRestore()
                captureSpy.mockRestore()
            }
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
            // event also satisfies the workflow's exit-on-conversion goal, which is independent of
            // currentAction - that wake must still happen.
            matcher.wakeRows = [{ ...matcher.findRows[0], state: stateBuffer({}) }]
            matcher.updateRowCount = 1
            matcher.setHogFlows({
                'flow-1': makeHogFlow({
                    id: 'flow-1',
                    exit_condition: 'exit_on_conversion',
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
            expect(newState.state.conversionCounted).toBe(true)
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

        it('sets conversionMatched and wakes the job when an exit_on_conversion goal fires', async () => {
            const flow = makeHogFlow({
                id: 'flow-1',
                exit_condition: 'exit_on_conversion',
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

            // exit_on_conversion wakes the job: a `SET scheduled = NOW()` UPDATE is issued.
            const wake = matcher.calls.find(
                (c) => c.sql.startsWith('UPDATE cyclotron_jobs') && c.sql.includes('SET scheduled = NOW()')
            )
            expect(wake).not.toBeUndefined()
            const newState = parseJSON(wake!.params[1][0].toString('utf-8')) as any
            expect(newState.state.conversionMatched).toBe(true)
            expect(newState.state.conversionCounted).toBe(true)
            // The conversion is also counted as a metric exactly once.
            expect(matcher.queueAppMetricMock).toHaveBeenCalledTimes(1)
            expect(matcher.queueAppMetricMock).toHaveBeenCalledWith(
                expect.objectContaining({ app_source_id: 'flow-1', metric_name: 'conversion', count: 1 }),
                'hog_flow'
            )
            // ...and emitted once as a billable $workflows_conversion event for the converting person.
            expect(matcher.queueConversionEventMock).toHaveBeenCalledTimes(1)
            expect(matcher.queueConversionEventMock).toHaveBeenCalledWith(
                expect.objectContaining({
                    team_id: 1,
                    event: '$workflows_conversion',
                    distinct_id: 'user-1',
                    properties: expect.objectContaining({
                        $workflow_id: 'flow-1',
                        $workflow_conversion_type: 'event',
                        $workflow_conversion_event: 'wuc_cancelled',
                    }),
                })
            )
        })

        it('does not wake on a conversion match when the workflow does not exit on conversion', async () => {
            // A conversion goal on an `exit_only_at_end` workflow is measurement-only: the conversion
            // event must NOT wake/resume the job (which would run its next step early, e.g. cut a
            // delay short). The conversion still counts once, persisted via a state-only UPDATE that
            // leaves `scheduled` untouched.
            const flow = makeHogFlow({
                id: 'flow-1',
                exit_condition: 'exit_only_at_end',
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
            // Event matches the conversion goal but not the wait step, so the only thing that could
            // wake the job is the conversion — which must be suppressed for exit_only_at_end.
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

            // No wake: no `SET scheduled = NOW()` UPDATE is issued.
            const wake = matcher.calls.find(
                (c) => c.sql.startsWith('UPDATE cyclotron_jobs') && c.sql.includes('SET scheduled = NOW()')
            )
            expect(wake).toBeUndefined()
            // But a state-only `SET state = u.state` UPDATE persists conversionCounted.
            const stateOnly = matcher.calls.find(
                (c) =>
                    c.sql.startsWith('UPDATE cyclotron_jobs') &&
                    c.sql.includes('SET state = u.state') &&
                    !c.sql.includes('scheduled')
            )
            expect(stateOnly).not.toBeUndefined()
            const newState = parseJSON(stateOnly!.params[1][0].toString('utf-8')) as any
            expect(newState.state.conversionCounted).toBe(true)
            expect(newState.state.conversionMatched).toBeUndefined()
            // ...and the conversion is counted once (measurement-only).
            expect(matcher.queueAppMetricMock).toHaveBeenCalledTimes(1)
            expect(matcher.queueAppMetricMock).toHaveBeenCalledWith(
                expect.objectContaining({ app_source_id: 'flow-1', metric_name: 'conversion', count: 1 }),
                'hog_flow'
            )
        })

        it('counts a conversion (without waking) for a conversion-only flow that has no wait step', async () => {
            // Broadened gating: a flow whose only actionable feature is an event-based conversion goal
            // (no wait_until_condition) is now evaluated regardless of exit condition, so the metric is
            // tracked. exit_only_at_end means it must not be woken.
            const flow = makeHogFlow({
                id: 'flow-1',
                waitUntil: false,
                exit_condition: 'exit_only_at_end',
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
                    action_id: null,
                    distinct_id: 'user-1',
                    person_id: null,
                },
            ]
            matcher.wakeRows = [{ ...matcher.findRows[0], state: stateBuffer({}) }]
            matcher.updateRowCount = 1
            matcher.setHogFlows({ 'flow-1': flow })

            await matcher.runWake([makeGlobals({ event: { ...makeGlobals({}).event, event: 'wuc_cancelled' } })])

            // No wake, but a state-only UPDATE persists conversionCounted.
            const wake = matcher.calls.find(
                (c) => c.sql.startsWith('UPDATE cyclotron_jobs') && c.sql.includes('SET scheduled = NOW()')
            )
            expect(wake).toBeUndefined()
            const stateOnly = matcher.calls.find(
                (c) =>
                    c.sql.startsWith('UPDATE cyclotron_jobs') &&
                    c.sql.includes('SET state = u.state') &&
                    !c.sql.includes('scheduled')
            )
            expect(stateOnly).not.toBeUndefined()
            expect(matcher.queueAppMetricMock).toHaveBeenCalledTimes(1)
            expect(matcher.queueAppMetricMock).toHaveBeenCalledWith(
                expect.objectContaining({ app_source_id: 'flow-1', metric_name: 'conversion', count: 1 }),
                'hog_flow'
            )
        })

        it('does not re-count or update a conversion already counted this run (per-run dedup)', async () => {
            // The parked job's state already carries conversionCounted: true (the run converted via a
            // property change, or an earlier matcher pass). A matching conversion event must be a
            // no-op: no metric, no UPDATE. The FOR UPDATE read sees the persisted flag and skips.
            const flow = makeHogFlow({
                id: 'flow-1',
                waitUntil: false,
                exit_condition: 'exit_only_at_end',
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
                    action_id: null,
                    distinct_id: 'user-1',
                    person_id: null,
                },
            ]
            matcher.wakeRows = [
                {
                    ...matcher.findRows[0],
                    state: stateBuffer({ currentAction: { id: 'wait_node' }, conversionCounted: true }),
                },
            ]
            matcher.updateRowCount = 1
            matcher.setHogFlows({ 'flow-1': flow })

            await matcher.runWake([makeGlobals({ event: { ...makeGlobals({}).event, event: 'wuc_cancelled' } })])

            const update = matcher.calls.find((c) => c.sql.startsWith('UPDATE cyclotron_jobs'))
            expect(update).toBeUndefined()
            expect(matcher.queueAppMetricMock).not.toHaveBeenCalled()
        })

        it('attributes a conversion to the batch parent_run_id when set', async () => {
            // Batch-workflow jobs carry a parent_run_id (the batch job). The emitted conversion metric
            // must key app_source_id by that run id, not the function id, so it lands under the batch.
            const flow = makeHogFlow({
                id: 'flow-1',
                waitUntil: false,
                exit_condition: 'exit_only_at_end',
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
                    parent_run_id: 'batch-run-1',
                    action_id: null,
                    distinct_id: 'user-1',
                    person_id: null,
                },
            ]
            matcher.wakeRows = [{ ...matcher.findRows[0], state: stateBuffer({}) }]
            matcher.updateRowCount = 1
            matcher.setHogFlows({ 'flow-1': flow })

            await matcher.runWake([makeGlobals({ event: { ...makeGlobals({}).event, event: 'wuc_cancelled' } })])

            expect(matcher.queueAppMetricMock).toHaveBeenCalledTimes(1)
            expect(matcher.queueAppMetricMock).toHaveBeenCalledWith(
                expect.objectContaining({
                    app_source_id: 'batch-run-1',
                    instance_id: 'flow-1',
                    metric_name: 'conversion',
                    count: 1,
                }),
                'hog_flow'
            )
        })

        it('does not wake on an empty conversion "events" entry (always-true bytecode)', async () => {
            // A conversion entry that targets neither events nor actions compiles to always-true
            // bytecode and would otherwise mark every incoming event as a conversion.
            const flow = makeHogFlow({
                id: 'flow-1',
                conversion: { events: [{ filters: { bytecode: ['_H', 1, 29], events: [] } }] } as any,
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
            // Wire the wake path so that IF the empty entry incorrectly matched, an UPDATE would
            // be produced — otherwise this assertion would pass trivially.
            matcher.wakeRows = [{ ...matcher.findRows[0], state: stateBuffer({ currentAction: { id: 'wait_node' } }) }]
            matcher.updateRowCount = 1
            matcher.setHogFlows({ 'flow-1': flow })

            await matcher.runWake([makeGlobals({ event: { ...makeGlobals({}).event, event: 'unrelated_event' } })])

            const update = matcher.calls.find((c) => c.sql.startsWith('UPDATE cyclotron_jobs'))
            expect(update).toBeUndefined()
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

        it('does not wake on an empty "events to wait for" entry (always-true bytecode)', async () => {
            // An events entry that references no events compiles to always-true bytecode and would
            // otherwise wake the job on any incoming event, bypassing the property condition.
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
            // Wire the wake path so that IF the empty entry incorrectly matched, an UPDATE would
            // be produced — otherwise this assertion would pass trivially.
            matcher.wakeRows = [{ ...matcher.findRows[0], state: stateBuffer({ currentAction: { id: 'wait_node' } }) }]
            matcher.updateRowCount = 1
            matcher.setHogFlows({
                'flow-1': makeHogFlow({
                    id: 'flow-1',
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
                                // Empty events entry: bytecode is TRUE (op 29), events list is empty.
                                events: [{ filters: { bytecode: ['_H', 1, 29], events: [] } }],
                                condition: { filters: null },
                                max_wait_duration: '5m',
                            },
                        },
                        { id: 'exit_node', name: 'Exit', type: 'exit', config: {} },
                    ],
                } as any),
            })

            await matcher.runWake([makeGlobals({ event: { ...makeGlobals({}).event, event: 'unrelated_event' } })])

            const update = matcher.calls.find((c) => c.sql.startsWith('UPDATE cyclotron_jobs'))
            expect(update).toBeUndefined()
        })

        it('does not wake on an empty property condition (always-true bytecode)', async () => {
            // A condition with no properties compiles to always-true bytecode and would otherwise
            // wake the job on any incoming event, bypassing the events the wait is configured for.
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
            matcher.setHogFlows({
                'flow-1': makeHogFlow({
                    id: 'flow-1',
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
                                            events: [
                                                {
                                                    id: 'wuc_subscribed',
                                                    name: 'wuc_subscribed',
                                                    type: 'events',
                                                    order: 0,
                                                },
                                            ],
                                        },
                                    },
                                ],
                                // Empty property condition: bytecode is TRUE (op 29), no properties.
                                condition: { filters: { bytecode: ['_H', 1, 29], properties: [] } },
                                max_wait_duration: '5m',
                            },
                        },
                        { id: 'exit_node', name: 'Exit', type: 'exit', config: {} },
                    ],
                } as any),
            })

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

        describe('agent_task steps', () => {
            const parkedAgentTaskJob = (taskRunId: string): void => {
                matcher.findRows = [
                    {
                        id: 'job-1',
                        team_id: 1,
                        function_id: 'flow-1',
                        action_id: 'agent_node',
                        distinct_id: 'user-1',
                        person_id: null,
                    },
                ]
                matcher.wakeRows = [
                    {
                        ...matcher.findRows[0],
                        state: stateBuffer({ currentAction: { id: 'agent_node', agentTaskState: { taskRunId } } }),
                    },
                ]
                matcher.updateRowCount = 1
                matcher.setHogFlows({ 'flow-1': makeAgentTaskFlow('flow-1') })
            }

            it('wakes a parked agent_task job when a matching task completion arrives', async () => {
                parkedAgentTaskJob('run-1')

                await matcher.runWake(
                    [makeTaskCompletionEvent('run-1', 'completed', { pr_url: 'https://x' })],
                    'internal_events'
                )

                const update = matcher.calls.find(
                    (c) => c.sql.startsWith('UPDATE cyclotron_jobs') && c.sql.includes('SET scheduled = NOW()')
                )
                expect(update).not.toBeUndefined()
                expect(update!.params[0]).toEqual(['job-1'])
                const newState = parseJSON(update!.params[1][0].toString('utf-8')) as any
                expect(newState.state.currentAction.agentTaskState).toEqual({
                    taskRunId: 'run-1',
                    completed: true,
                    status: 'completed',
                    output: { pr_url: 'https://x' },
                })
            })

            it('does not wake a job whose stored task run id differs (shared distinct_id)', async () => {
                // The parked job waits on run-2, but a completion for run-1 (same person) arrives.
                parkedAgentTaskJob('run-2')

                await matcher.runWake([makeTaskCompletionEvent('run-1', 'completed', null)], 'internal_events')

                const update = matcher.calls.find(
                    (c) => c.sql.startsWith('UPDATE cyclotron_jobs') && c.sql.includes('SET scheduled = NOW()')
                )
                expect(update).toBeUndefined()
            })

            it('is not woken by the same completion event on the events firehose', async () => {
                // agent_task flows are only actionable on the internal-events stream, so the events
                // source must skip cyclotron entirely for a team that has only an agent_task flow.
                parkedAgentTaskJob('run-1')

                await matcher.runWake([makeTaskCompletionEvent('run-1', 'completed', null)], 'events')

                expect(matcher.calls.find((c) => c.sql.includes('SELECT id, team_id, function_id'))).toBeUndefined()
            })
        })
    })

    describe('_parseKafkaBatch', () => {
        const rawMessage = (overrides: Record<string, any>): any => ({
            value: Buffer.from(
                JSON.stringify({
                    uuid: 'e-uuid',
                    event: 'wuc_subscribed',
                    team_id: 1,
                    distinct_id: 'user-1',
                    person_id: 'person-uuid-1',
                    timestamp: '2024-01-01 00:00:00.000',
                    properties: '{}',
                    elements_chain: '',
                    ...overrides,
                })
            ),
        })

        beforeEach(() => {
            ;(matcher as any).deps = {
                teamManager: {
                    getTeam: jest.fn().mockResolvedValue({ id: 1, name: 'Test', person_display_name_properties: null }),
                },
            }
            ;(matcher as any).config = { SITE_URL: 'http://localhost:8000' }
            // Team 1 has an actionable (wait_until_condition) flow so events reach conversion.
            matcher.setHogFlows({ 'flow-1': makeHogFlow({ id: 'flow-1', team_id: 1 }) })
        })

        it('keeps events with a distinct_id but no person_id, drops events with neither', async () => {
            // A job can be parked by distinct_id alone (the lookup has a (team_id, distinct_id)
            // branch), so an event carrying only a distinct_id must still flow into matching.
            const result = await (matcher as any)._parseKafkaBatch([
                rawMessage({ person_id: '', distinct_id: 'only-distinct' }),
                rawMessage({ person_id: '', distinct_id: '' }),
                rawMessage({ person_id: 'person-uuid-1', distinct_id: 'user-1' }),
            ])

            const distinctIds = result.map((g: HogFunctionInvocationGlobals) => g.event.distinct_id).sort()
            expect(distinctIds).toEqual(['only-distinct', 'user-1'])

            // The distinct-only event has no resolved person, which downstream indexing handles.
            const distinctOnly = result.find(
                (g: HogFunctionInvocationGlobals) => g.event.distinct_id === 'only-distinct'
            )!
            expect(distinctOnly.person).toBeUndefined()
        })

        it('skips events whose team has no actionable flow before paying for getTeam + conversion', async () => {
            // Team 2 has no wait_until_condition step and no event conversion goal, so its events
            // must be dropped via the in-memory cache without ever calling getTeam or converting.
            const getTeam = (matcher as any).deps.teamManager.getTeam

            const result = await (matcher as any)._parseKafkaBatch([
                rawMessage({ team_id: 2, distinct_id: 'user-2' }),
                rawMessage({ team_id: 1, distinct_id: 'user-1' }),
            ])

            expect(result.map((g: HogFunctionInvocationGlobals) => g.project.id)).toEqual([1])
            // getTeam is only reached for the actionable team, never for team 2.
            expect(getTeam).toHaveBeenCalledTimes(1)
            expect(getTeam).toHaveBeenCalledWith(1)
        })
    })

    describe('_parsePersonBatch', () => {
        const rawPerson = (overrides: Record<string, any>): any => ({
            value: Buffer.from(
                JSON.stringify({
                    id: 'person-uuid-1',
                    team_id: 1,
                    properties: JSON.stringify({ plan: 'enterprise' }),
                    is_deleted: 0,
                    timestamp: '2024-01-01 00:00:00.000',
                    ...overrides,
                })
            ),
        })

        beforeEach(() => {
            ;(matcher as any).deps = {
                teamManager: {
                    getTeam: jest.fn().mockResolvedValue({ id: 1, name: 'Test', person_display_name_properties: null }),
                },
            }
            ;(matcher as any).config = { SITE_URL: 'http://localhost:8000' }
            matcher.setHogFlows({ 'flow-1': makeHogFlow({ id: 'flow-1', team_id: 1 }) })
        })

        it('maps a person mutation to $person_updated globals keyed on person_id only', async () => {
            const result = await (matcher as any)._parsePersonBatch([rawPerson({})])

            expect(result).toHaveLength(1)
            const globals = result[0] as HogFunctionInvocationGlobals
            expect(globals.event.event).toBe('$person_updated')
            // distinct_id is empty so indexBatch keys this only on person_id, never adding a spurious
            // (team_id, distinct_id) lookup.
            expect(globals.event.distinct_id).toBe('')
            expect(globals.person?.id).toBe('person-uuid-1')
            expect(globals.person?.properties).toEqual({ plan: 'enterprise' })
        })

        it('skips deleted persons, persons with no id, and persons whose team has no actionable flow', async () => {
            const getTeam = (matcher as any).deps.teamManager.getTeam

            const result = await (matcher as any)._parsePersonBatch([
                rawPerson({ is_deleted: 1 }),
                rawPerson({ id: '' }),
                rawPerson({ team_id: 2 }), // team 2 has no wait_until_condition flow
                rawPerson({}),
            ])

            // Only the valid person for the actionable team survives.
            expect(result.map((g: HogFunctionInvocationGlobals) => g.person?.id)).toEqual(['person-uuid-1'])
            // The firehose early-out means getTeam is only paid for the surviving person.
            expect(getTeam).toHaveBeenCalledTimes(1)
            expect(getTeam).toHaveBeenCalledWith(1)
        })

        it('skips a person whose team cannot be loaded', async () => {
            ;(matcher as any).deps.teamManager.getTeam = jest.fn().mockResolvedValue(null)

            const result = await (matcher as any)._parsePersonBatch([rawPerson({})])

            expect(result).toEqual([])
        })
    })

    describe('_parseInternalEventsBatch', () => {
        const rawInternalEvent = (
            overrides: { team_id?: number; event?: Record<string, any>; person?: any } = {}
        ): any => ({
            value: Buffer.from(
                JSON.stringify({
                    team_id: overrides.team_id ?? 1,
                    event: {
                        uuid: 'evt-uuid-1',
                        event: '$insight_alert_firing',
                        distinct_id: 'distinct-1',
                        properties: {},
                        timestamp: '2024-01-01T00:00:00Z',
                        ...overrides.event,
                    },
                    ...(overrides.person !== undefined ? { person: overrides.person } : {}),
                })
            ),
        })

        beforeEach(() => {
            ;(matcher as any).deps = {
                teamManager: {
                    getTeam: jest.fn().mockResolvedValue({ id: 1, name: 'Test', person_display_name_properties: null }),
                },
            }
            ;(matcher as any).config = { SITE_URL: 'http://localhost:8000' }
            matcher.setHogFlows({ 'flow-1': makeHogFlow({ id: 'flow-1', team_id: 1 }) })
        })

        it('maps an internal event to globals keyed on distinct_id', async () => {
            const result = await (matcher as any)._parseInternalEventsBatch([rawInternalEvent()])

            expect(result).toHaveLength(1)
            const globals = result[0] as HogFunctionInvocationGlobals
            expect(globals.event.event).toBe('$insight_alert_firing')
            expect(globals.event.distinct_id).toBe('distinct-1')
        })

        it('skips events with no identifiers and no-flow teams, but keeps a person-only event', async () => {
            const result = await (matcher as any)._parseInternalEventsBatch([
                rawInternalEvent({ event: { distinct_id: '' } }), // no distinct_id and no person
                rawInternalEvent({ team_id: 2 }), // team 2 has no actionable flow
                rawInternalEvent({ event: { distinct_id: '' }, person: { id: 'person-1', properties: {} } }),
            ])

            // Only the person-only event for the actionable team survives — matched later by person_id.
            expect(result).toHaveLength(1)
            expect((result[0] as HogFunctionInvocationGlobals).person?.id).toBe('person-1')
        })

        it('skips an event whose team cannot be loaded', async () => {
            ;(matcher as any).deps.teamManager.getTeam = jest.fn().mockResolvedValue(null)

            const result = await (matcher as any)._parseInternalEventsBatch([rawInternalEvent()])

            expect(result).toEqual([])
        })

        it('drops a malformed message (schema parse failure) without throwing', async () => {
            const result = await (matcher as any)._parseInternalEventsBatch([
                { value: Buffer.from(JSON.stringify({ team_id: 1 })) }, // missing required `event`
                rawInternalEvent(),
            ])

            // The bad message is dropped; the valid one still parses.
            expect(result).toHaveLength(1)
            expect((result[0] as HogFunctionInvocationGlobals).event.event).toBe('$insight_alert_firing')
        })
    })

    // The full combination matrix lives here (mocked pg, ~ms each) rather than in the E2E suite:
    // it exercises the same wake decision the matcher makes for every events/property/action shape.
    describe('wake matrix: events / property / action combinations', () => {
        const ALWAYS_TRUE = ['_H', 1, 29]
        // Real, serializer-compiled bytecode for event.properties.plan == 'growth'.
        const PROPERTY_BYTECODE = ['_H', 1, 32, 'growth', 32, 'plan', 32, 'properties', 1, 2, 11]

        const eventEntry = { filters: { bytecode: eventBytecode('wakeup_event'), events: [{ id: 'wakeup_event' }] } }
        const actionEntry = {
            filters: { bytecode: eventBytecode('action_event'), events: [], actions: [{ id: 3, type: 'actions' }] },
        }
        const emptyEventEntry = { filters: { bytecode: ALWAYS_TRUE, events: [] } }
        const propertyCondition = {
            filters: {
                bytecode: PROPERTY_BYTECODE,
                properties: [{ key: 'plan', type: 'event', value: 'growth', operator: 'exact' }],
            },
        }
        const emptyCondition = { filters: { bytecode: ALWAYS_TRUE, properties: [] } }
        // A real condition expressed through an events-shaped filter (no top-level `properties`).
        // Guards the regression where the guard keyed on `properties` and skipped this as "empty".
        const eventShapedCondition = {
            filters: { bytecode: eventBytecode('special_event'), events: [{ id: 'special_event' }] },
        }

        const wakeWith = (event: string, properties: Record<string, any> = {}): HogFunctionInvocationGlobals =>
            makeGlobals({ event: { ...makeGlobals({}).event, event, properties } })
        const matchingEvent = (): HogFunctionInvocationGlobals => wakeWith('wakeup_event')
        const actionEvent = (): HogFunctionInvocationGlobals => wakeWith('action_event')
        const propertyEvent = (): HogFunctionInvocationGlobals => wakeWith('some_event', { plan: 'growth' })
        const unrelatedEvent = (): HogFunctionInvocationGlobals => wakeWith('unrelated_event', { plan: 'starter' })

        interface WakeCase {
            name: string
            config: Record<string, any>
            event: () => HogFunctionInvocationGlobals
            woken: boolean
        }

        const cases: WakeCase[] = [
            // ---- real combinations that SHOULD wake ----
            {
                name: 'event only + matching event',
                config: { events: [eventEntry] },
                event: matchingEvent,
                woken: true,
            },
            {
                name: 'property only + satisfying event',
                config: { condition: propertyCondition },
                event: propertyEvent,
                woken: true,
            },
            {
                name: 'event + property + matching event',
                config: { events: [eventEntry], condition: propertyCondition },
                event: matchingEvent,
                woken: true,
            },
            {
                name: 'event + property + satisfying event',
                config: { events: [eventEntry], condition: propertyCondition },
                event: propertyEvent,
                woken: true,
            },
            {
                name: 'action only + action event',
                config: { events: [actionEntry] },
                event: actionEvent,
                woken: true,
            },
            {
                name: 'action + property + action event',
                config: { events: [actionEntry], condition: propertyCondition },
                event: actionEvent,
                woken: true,
            },
            {
                name: 'action + property + satisfying event',
                config: { events: [actionEntry], condition: propertyCondition },
                event: propertyEvent,
                woken: true,
            },
            {
                name: 'event + empty property (suppressed) + matching event',
                config: { events: [eventEntry], condition: emptyCondition },
                event: matchingEvent,
                woken: true,
            },
            {
                name: 'empty events (suppressed) + property + satisfying event',
                config: { events: [emptyEventEntry], condition: propertyCondition },
                event: propertyEvent,
                woken: true,
            },
            {
                name: 'condition via events shape (no properties) + matching event',
                config: { condition: eventShapedCondition },
                event: () => wakeWith('special_event'),
                woken: true,
            },
            // ---- combinations that must NOT wake ----
            {
                name: 'event only + unrelated event',
                config: { events: [eventEntry] },
                event: unrelatedEvent,
                woken: false,
            },
            {
                name: 'property only + unrelated event',
                config: { condition: propertyCondition },
                event: unrelatedEvent,
                woken: false,
            },
            {
                name: 'event + property + unrelated event',
                config: { events: [eventEntry], condition: propertyCondition },
                event: unrelatedEvent,
                woken: false,
            },
            {
                name: 'empty property only + unrelated event',
                config: { condition: emptyCondition },
                event: unrelatedEvent,
                woken: false,
            },
            {
                name: 'empty events only + unrelated event',
                config: { events: [emptyEventEntry] },
                event: unrelatedEvent,
                woken: false,
            },
            {
                name: 'empty events + empty property + unrelated event',
                config: { events: [emptyEventEntry], condition: emptyCondition },
                event: unrelatedEvent,
                woken: false,
            },
        ]

        it.each(cases)('$name -> woken: $woken', async ({ config, event, woken }) => {
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
            // Wire the wake path so that IF the job is woken, an UPDATE is produced.
            matcher.wakeRows = [{ ...matcher.findRows[0], state: stateBuffer({ currentAction: { id: 'wait_node' } }) }]
            matcher.updateRowCount = 1
            matcher.setHogFlows({
                'flow-1': makeHogFlow({
                    id: 'flow-1',
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
                            config: { max_wait_duration: '5m', ...config },
                        },
                        { id: 'exit_node', name: 'Exit', type: 'exit', config: {} },
                    ],
                } as any),
            })

            await matcher.runWake([event()])

            const update = matcher.calls.find((c) => c.sql.startsWith('UPDATE cyclotron_jobs'))
            if (woken) {
                expect(update).toBeDefined()
            } else {
                expect(update).toBeUndefined()
            }
        })
    })
})
