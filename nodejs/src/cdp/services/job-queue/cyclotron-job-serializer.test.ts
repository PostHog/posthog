import { DateTime } from 'luxon'
import { v4 as uuidv4 } from 'uuid'

import { parseJSON } from '~/utils/json-parse'

import { CyclotronJobInvocation, CyclotronJobInvocationResult } from '../../types'
import { CyclotronV2DequeuedJob } from '../cyclotron-v2'
import { CyclotronJobSerializer, extractActionId, extractDistinctId, extractPersonId } from './cyclotron-job-serializer'

describe('CyclotronJobSerializer', () => {
    let serializer: CyclotronJobSerializer

    beforeEach(() => {
        serializer = new CyclotronJobSerializer()
    })

    const exampleGlobals = (): Record<string, any> => ({
        project: { id: 1, name: 'p', url: 'http://localhost' },
        source: { name: 'fn', url: 'http://localhost/fn' },
        event: {
            uuid: 'e-1',
            event: '$pageview',
            distinct_id: 'd-1',
            properties: {},
            elements_chain: '',
            timestamp: '2026-05-01T00:00:00Z',
            url: 'http://localhost',
        },
        person: { id: 'person-1', name: 'x', url: 'http://localhost', properties: { email: 'a@b.com' } },
        groups: {
            organization: { id: 'org-1', type: 'organization', index: 0, url: 'http://localhost', properties: {} },
        },
        inputs: { api_key: 'sk-secret', url: 'https://example.com' },
    })

    const hogFunctionInvocation = (overrides: Partial<CyclotronJobInvocation> = {}): CyclotronJobInvocation => ({
        id: uuidv4(),
        teamId: 1,
        functionId: 'fn-1',
        queue: 'hog',
        queuePriority: 0,
        state: { globals: exampleGlobals(), vmState: { stack: [] }, timings: [], attempts: 0 },
        ...overrides,
    })

    const makeDequeuedJob = (overrides: Partial<Record<string, any>> = {}): CyclotronV2DequeuedJob =>
        ({
            id: uuidv4(),
            teamId: 1,
            functionId: 'fn-1',
            queueName: 'hog',
            priority: 0,
            scheduled: DateTime.now(),
            created: DateTime.now(),
            parentRunId: null,
            transitionCount: 0,
            state: null,
            distinctId: null,
            personId: null,
            actionId: null,
            ack: jest.fn(),
            fail: jest.fn(),
            reschedule: jest.fn(),
            cancel: jest.fn(),
            heartbeat: jest.fn(),
            ...overrides,
        }) as CyclotronV2DequeuedJob

    describe('stripForPersistence', () => {
        it('drops inputs, person and groups from a hog function state.globals', () => {
            const stripped = serializer.stripForPersistence(hogFunctionInvocation())
            expect(stripped.state!.globals.inputs).toBeUndefined()
            expect(stripped.state!.globals.person).toBeUndefined()
            expect(stripped.state!.globals.groups).toBeUndefined()
        })

        it('keeps the raw event, project and source — these are not derivable', () => {
            const inv = hogFunctionInvocation()
            const stripped = serializer.stripForPersistence(inv)
            expect(stripped.state!.globals.event).toEqual(inv.state!.globals.event)
            expect(stripped.state!.globals.project).toEqual(inv.state!.globals.project)
            expect(stripped.state!.globals.source).toEqual(inv.state!.globals.source)
            expect(stripped.state!.vmState).toEqual(inv.state!.vmState)
        })

        it('does not mutate the original invocation', () => {
            const inv = hogFunctionInvocation()
            serializer.stripForPersistence(inv)
            expect(inv.state!.globals.inputs).toBeDefined()
            expect(inv.state!.globals.person).toBeDefined()
            expect(inv.state!.globals.groups).toBeDefined()
        })

        it('returns the same reference when there is nothing to strip', () => {
            const inv: CyclotronJobInvocation = {
                ...hogFunctionInvocation(),
                state: { globals: { event: { uuid: 'e' } }, timings: [] },
            }
            expect(serializer.stripForPersistence(inv)).toBe(inv)
        })

        it('returns the same reference for a null state', () => {
            const inv: CyclotronJobInvocation = { ...hogFunctionInvocation(), state: null }
            expect(serializer.stripForPersistence(inv)).toBe(inv)
        })

        it('strips the nested hog function globals a hog flow carries mid-async', () => {
            const inv: CyclotronJobInvocation = {
                id: uuidv4(),
                teamId: 1,
                functionId: 'flow-1',
                queue: 'hogflow',
                queuePriority: 0,
                state: {
                    event: { uuid: 'e-1', distinct_id: 'd-1', properties: {} },
                    actionStepCount: 1,
                    currentAction: {
                        id: 'action-1',
                        startedAtTimestamp: 0,
                        hogFunctionState: { globals: exampleGlobals(), timings: [], attempts: 0 },
                    },
                },
            }
            const stripped = serializer.stripForPersistence(inv)
            const nested = stripped.state!.currentAction.hogFunctionState.globals
            expect(nested.inputs).toBeUndefined()
            expect(nested.person).toBeUndefined()
            expect(nested.groups).toBeUndefined()
            expect(nested.event).toBeDefined()
            // The hog flow's own raw event is untouched.
            expect(stripped.state!.event).toEqual(inv.state!.event)
            // Original is not mutated.
            expect(inv.state!.currentAction.hogFunctionState.globals.inputs).toBeDefined()
        })
    })

    describe('stripResultsForPersistence', () => {
        it('strips each result invocation', () => {
            const result: CyclotronJobInvocationResult = {
                invocation: hogFunctionInvocation(),
                finished: false,
                logs: [],
                metrics: [],
                capturedPostHogEvents: [],
                warehouseWebhookPayloads: [],
            }
            const [stripped] = serializer.stripResultsForPersistence([result])
            expect(stripped.invocation.state!.globals.inputs).toBeUndefined()
        })
    })

    describe('kafka', () => {
        it('serializes to JSON with derived globals removed but the event kept', () => {
            const parsed = parseJSON(serializer.serializeForKafka(hogFunctionInvocation())) as any
            expect(parsed.state.globals.inputs).toBeUndefined()
            expect(parsed.state.globals.person).toBeUndefined()
            expect(parsed.state.globals.groups).toBeUndefined()
            expect(parsed.state.globals.event).toBeDefined()
        })

        it('drops transient top-level props (hogFunction, person, filterGlobals)', () => {
            const inv = {
                ...hogFunctionInvocation(),
                hogFunction: { id: 'x' },
                person: { id: 'p' },
                filterGlobals: {},
            } as any
            const parsed = parseJSON(serializer.serializeForKafka(inv)) as any
            expect(parsed.hogFunction).toBeUndefined()
            expect(parsed.person).toBeUndefined()
            expect(parsed.filterGlobals).toBeUndefined()
        })

        it('round-trips an invocation back through deserializeFromKafka', () => {
            const inv = hogFunctionInvocation()
            const out = serializer.deserializeFromKafka(serializer.serializeForKafka(inv))
            expect(out.id).toBe(inv.id)
            expect(out.queueSource).toBe('kafka')
            expect(out.state!.globals.event).toEqual(inv.state!.globals.event)
            expect(out.state!.globals.inputs).toBeUndefined()
        })

        it('migrates a legacy job (top-level hogFunctionId / vmState / globals)', () => {
            const legacy = {
                id: 'inv-1',
                teamId: 1,
                queue: 'hog',
                queuePriority: 0,
                hogFunctionId: 'fn-legacy',
                globals: { event: { event: 'foo' } },
                vmState: { stack: [] },
                timings: [{ kind: 'hog', duration_ms: 1 }],
            }
            const out = serializer.deserializeFromKafka(JSON.stringify(legacy))
            expect(out.functionId).toBe('fn-legacy')
            expect((out as any).hogFunctionId).toBeUndefined()
            expect(out.state!.vmState).toEqual({ stack: [] })
            expect(out.state!.globals).toEqual({ event: { event: 'foo' } })
            expect(out.state!.timings).toEqual([{ kind: 'hog', duration_ms: 1 }])
            expect(out.queueSource).toBe('kafka')
        })
    })

    describe('postgres-v2', () => {
        it('serializes a stripped state blob plus lookup columns', () => {
            const inv = hogFunctionInvocation()
            const job = serializer.serializeForPostgresV2(inv)
            expect(job.id).toBe(inv.id)
            expect(job.teamId).toBe(inv.teamId)
            expect(job.queueName).toBe('hog')
            const blob = parseJSON(job.state!.toString('utf-8')) as any
            expect(blob.state.globals.inputs).toBeUndefined()
            expect(blob.state.globals.event.uuid).toBe('e-1')
        })

        it('round-trips through deserializeFromPostgresV2', () => {
            const inv = hogFunctionInvocation()
            const job = serializer.serializeForPostgresV2(inv)
            const out = serializer.deserializeFromPostgresV2(makeDequeuedJob({ id: inv.id, state: job.state }))
            expect(out.id).toBe(inv.id)
            expect(out.queueSource).toBe('postgres-v2')
            expect(out.state!.globals.event).toEqual(inv.state!.globals.event)
            expect(out.state!.globals.inputs).toBeUndefined()
        })

        it('serializeStateForPostgresV2 strips globals and keeps queueParameters/queueMetadata', () => {
            const inv: CyclotronJobInvocation = {
                ...hogFunctionInvocation(),
                queueParameters: { type: 'fetch' } as any,
                queueMetadata: { tries: 1 },
            }
            const blob = parseJSON(serializer.serializeStateForPostgresV2(inv).toString('utf-8')) as any
            expect(blob.state.globals.inputs).toBeUndefined()
            expect(blob.queueParameters).toEqual({ type: 'fetch' })
            expect(blob.queueMetadata).toEqual({ tries: 1 })
        })

        it('tolerates an unparseable state blob', () => {
            const out = serializer.deserializeFromPostgresV2(makeDequeuedJob({ state: Buffer.from('not json') }))
            expect(out.state).toBeNull()
        })
    })

    describe('extractDistinctId', () => {
        const cases: Array<[string, any, string | null]> = [
            ['returns event.distinct_id', { state: { event: { distinct_id: 'u-1' } } }, 'u-1'],
            ['null when state has no event', { state: { personId: 'p' } }, null],
            ['null when state is null', { state: null }, null],
            ['null for empty event.distinct_id', { state: { event: { distinct_id: '' } } }, null],
        ]
        it.each(cases)('%s', (_desc, overrides, expected) => {
            expect(extractDistinctId({ ...overrides } as CyclotronJobInvocation)).toBe(expected)
        })
    })

    describe('extractPersonId', () => {
        const cases: Array<[string, any, string | null]> = [
            ['returns invocation.person.id', { person: { id: 'p-evt' }, state: {} }, 'p-evt'],
            ['falls back to state.personId', { state: { personId: 'p-batch' } }, 'p-batch'],
            ['prefers person.id over state.personId', { person: { id: 'p-evt' }, state: { personId: 'p-b' } }, 'p-evt'],
            ['null when neither present', { state: { globals: {} } }, null],
            ['null when state is null', { state: null }, null],
        ]
        it.each(cases)('%s', (_desc, overrides, expected) => {
            expect(extractPersonId({ ...overrides } as CyclotronJobInvocation)).toBe(expected)
        })
    })

    describe('extractActionId', () => {
        const cases: Array<[string, any, string | null]> = [
            ['returns currentAction.id', { state: { currentAction: { id: 'a-1' } } }, 'a-1'],
            ['null when currentAction absent', { state: { event: {} } }, null],
            ['null when state is null', { state: null }, null],
            ['null when currentAction.id is empty', { state: { currentAction: { id: '' } } }, null],
        ]
        it.each(cases)('%s', (_desc, overrides, expected) => {
            expect(extractActionId({ ...overrides } as CyclotronJobInvocation)).toBe(expected)
        })
    })
})
