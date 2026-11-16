import { logger } from '~/common/utils/logger'

import { createExampleInvocation } from '../_tests/fixtures'
import { resetHogvmNodeModuleCacheForTests } from './rust-vm'
import {
    MAX_REGISTERED_PROGRAMS,
    RustVmExecutor,
    rustVmExecution,
    rustVmProgramRegistrations,
} from './rust-vm-executor'

jest.mock('@posthog/hogvm-node', () => ({
    init: jest.fn(),
    executeSync: jest.fn(),
    executeBatch: jest.fn(),
    registerProgram: jest.fn(),
    releaseProgram: jest.fn(),
    executeRegisteredSync: jest.fn(),
    executeRegisteredBatch: jest.fn(),
}))

const mockHogvmNode = jest.mocked(jest.requireMock<typeof import('@posthog/hogvm-node')>('@posthog/hogvm-node'))
const realHogvmNode = jest.requireActual<typeof import('@posthog/hogvm-node')>('@posthog/hogvm-node')

const rustResult = (overrides: Partial<ReturnType<typeof mockHogvmNode.executeSync>> = {}) => ({
    result: { properties: { a: 1 } },
    durationUs: 1500,
    logs: [],
    logsTruncated: false,
    ...overrides,
})

// Distinct bytecode per value: "_H" header, version 1, push int, RETURN.
const program = (value: number): unknown[] => ['_H', 1, 33, value, 38]
const COUNT_TO_20000 = ['_H', 1, 33, 0, 33, 20000, 36, 0, 15, 40, 9, 33, 1, 36, 0, 6, 37, 0, 39, -16, 36, 0, 38, 35]
const RETURN_EVENT_UUID = ['_H', 1, 32, 'uuid', 32, 'event', 1, 2, 38]
const printing = (...messages: string[]): unknown[] => [
    '_H',
    1,
    ...messages.flatMap((message) => [32, message, 2, 'print', 1, 35]),
    33,
    1,
    38,
]
const PRINT_30_TIMES = [
    '_H',
    1,
    33,
    0,
    33,
    30,
    36,
    0,
    15,
    40,
    15,
    36,
    0,
    2,
    'print',
    1,
    35,
    33,
    1,
    36,
    0,
    6,
    37,
    0,
    39,
    -22,
    33,
    1,
    38,
    35,
]
const DIVIDE_BY_ZERO = ['_H', 1, 33, 0, 33, 1, 9, 38]
const CALL_MESSAGING_PREFERENCES_URL = ['_H', 1, 2, 'generateMessagingPreferencesUrl', 0, 38]

const outcomeCount = async (outcome: string): Promise<number> =>
    (await rustVmExecution.get()).values.find((value) => value.labels.outcome === outcome)?.value ?? 0
const registrationCount = async (): Promise<number> => (await rustVmProgramRegistrations.get()).values[0]?.value ?? 0

const withoutBinding = async (binding: keyof typeof mockHogvmNode, run: () => Promise<void> | void): Promise<void> => {
    const original = mockHogvmNode[binding]
    delete mockHogvmNode[binding]
    try {
        await run()
    } finally {
        Object.assign(mockHogvmNode, { [binding]: original })
    }
}

describe('RustVmExecutor', () => {
    let executor: RustVmExecutor
    let liveHandles: Set<number>

    beforeEach(() => {
        jest.clearAllMocks()
        resetHogvmNodeModuleCacheForTests()
        rustVmExecution.reset()
        rustVmProgramRegistrations.reset()
        executor = new RustVmExecutor({ mmdb: { kind: 'file', path: process.env.MMDB_FILE_LOCATION! } })
        // `clearAllMocks` resets call data but not implementations, so a case that makes a mock
        // throw would leak into every case after it. Re-establish the working defaults here.
        liveHandles = new Set()
        mockHogvmNode.init.mockImplementation(realHogvmNode.init)
        mockHogvmNode.registerProgram.mockImplementation((bytecode) => {
            const handle = realHogvmNode.registerProgram(bytecode)
            liveHandles.add(handle)
            return handle
        })
        mockHogvmNode.releaseProgram.mockImplementation((handle) => {
            realHogvmNode.releaseProgram(handle)
            liveHandles.delete(handle)
        })
        mockHogvmNode.executeRegisteredSync.mockImplementation(realHogvmNode.executeRegisteredSync)
        mockHogvmNode.executeSync.mockImplementation(realHogvmNode.executeSync)
        mockHogvmNode.executeRegisteredBatch.mockImplementation(realHogvmNode.executeRegisteredBatch)
        mockHogvmNode.executeBatch.mockImplementation(realHogvmNode.executeBatch)
    })

    it.each([
        ['execute', 'its own step budget instead of the default 10_000', COUNT_TO_20000, 20000],
        ['execute', 'the invocation globals', RETURN_EVENT_UUID, 'event-1'],
        ['executeBatched', 'its own step budget instead of the default 10_000', COUNT_TO_20000, 20000],
        ['executeBatched', 'the invocation globals', RETURN_EVENT_UUID, 'event-1'],
    ] as const)(
        '%s runs the program on the rust vm against %s and returns a finished result',
        async (path, _against, bytecode, expected) => {
            const invocation = createExampleInvocation({ bytecode: [...bytecode] })
            invocation.state.globals.event.uuid = 'event-1'

            const result = await executor[path](invocation, [])

            expect(result).not.toBeNull()
            expect(result!.finished).toEqual(true)
            expect(result!.error).toBeUndefined()
            expect(result!.execResult).toEqual(expected)
            expect(result!.invocation.state.timings).toEqual([{ kind: 'hog', duration_ms: expect.any(Number) }])
            expect(liveHandles.size).toEqual(1)
        }
    )

    it('reports the native duration in milliseconds as the hog timing and in the completion log', () => {
        mockHogvmNode.executeRegisteredSync.mockReturnValue(rustResult())

        const result = executor.execute(createExampleInvocation(), [])

        expect(result!.invocation.state.timings).toEqual([{ kind: 'hog', duration_ms: 1.5 }])
        expect(result!.logs.map((log) => log.message)).toEqual(['Function completed in 1.5ms.'])
    })

    it('a null program result leaves execResult unset so the transformer drops the event', () => {
        const result = executor.execute(createExampleInvocation({ bytecode: ['_H', 1, 31, 38] }), [])

        expect(result!.error).toBeUndefined()
        expect(result!.execResult).toBeUndefined()
    })

    it('surfaces print() output as info logs with sensitive values redacted', () => {
        const invocation = createExampleInvocation({ bytecode: printing('token is secret-token', 'plain') })

        const result = executor.execute(invocation, ['secret-token'])

        expect(result!.logs.map((log) => [log.level, log.message])).toEqual([
            ['info', 'token is ***REDACTED***'],
            ['info', 'plain'],
            ['debug', expect.stringContaining('Function completed in')],
        ])
    })

    it('keeps the first 24 print() messages and warns that the rest were dropped', () => {
        const result = executor.execute(createExampleInvocation({ bytecode: PRINT_30_TIMES }), [])

        expect(result!.logs.map((log) => log.level)).toEqual([...Array(24).fill('info'), 'warn', 'debug'])
        expect(result!.logs.slice(0, 24).map((log) => log.message)).toEqual(
            Array.from({ length: 24 }, (_, i) => String(i))
        )
        expect(result!.logs[24].message).toContain('Function exceeded maximum log entries')
    })

    it("redacts each invocation's logs with its own sensitive values, not another invocation's", () => {
        const bytecode = printing('token is secret-a and secret-b')

        const first = executor.execute(createExampleInvocation({ bytecode }), ['secret-a'])
        const second = executor.execute(createExampleInvocation({ bytecode }), ['secret-b'])

        expect(first!.logs[0].message).toEqual('token is ***REDACTED*** and secret-b')
        expect(second!.logs[0].message).toEqual('token is secret-a and ***REDACTED***')
    })

    it('a rust execution error becomes the result error with an error log, without falling back', () => {
        const result = executor.execute(createExampleInvocation({ bytecode: DIVIDE_BY_ZERO }), [])

        expect(result).not.toBeNull()
        expect(result!.error).toEqual('Division by zero')
        expect(result!.finished).toEqual(true)
        expect(result!.execResult).toBeUndefined()
        expect(result!.logs.map((log) => log.level)).toEqual(['error'])
        expect(result!.logs[0].message).toContain('Division by zero')
    })

    it.each([
        ['unsupported host function', CALL_MESSAGING_PREFERENCES_URL],
        ['function missing from the rust vm', ['_H', 1, 32, 'x', 2, 'sendEmail', 1, 38]],
        ['global chain the rust vm cannot resolve', ['_H', 1, 32, 'foo', 32, 'inputs', 1, 2, 38]],
    ])('falls back to the node vm on %s', async (_name, bytecode) => {
        expect(executor.execute(createExampleInvocation({ bytecode }), [])).toBeNull()
        expect(await outcomeCount('fallback_unsupported')).toEqual(1)
    })

    it('falls back to the node vm on an input shape the rust vm has no implementation for', async () => {
        mockHogvmNode.executeRegisteredSync.mockReturnValue(
            rustResult({ result: undefined, error: 'Not implemented: extract of a value only luxon reads' })
        )

        expect(executor.execute(createExampleInvocation(), [])).toBeNull()
        expect(await outcomeCount('fallback_unsupported')).toEqual(1)
    })

    it('falls back to the node vm when the ffi boundary throws instead of returning an error', async () => {
        const invocation = createExampleInvocation({ bytecode: RETURN_EVENT_UUID })
        invocation.state.globals.event.properties.unrepresentable = NaN

        expect(executor.execute(invocation, [])).toBeNull()
        expect(await outcomeCount('fallback_exception')).toEqual(1)
    })

    it('redacts sensitive values from fallback logs', () => {
        // Marshalling errors and panic messages can embed values from the invocation globals.
        const warnSpy = jest.spyOn(logger, 'warn').mockImplementation(() => {})
        mockHogvmNode.executeRegisteredSync.mockImplementation(() => {
            throw new Error('failed to convert value "secret-token" at inputs')
        })

        expect(executor.execute(createExampleInvocation(), ['secret-token'])).toBeNull()

        const fallbackCalls = warnSpy.mock.calls.filter((call) => String(call[1]).includes('fell back'))
        expect(fallbackCalls).toHaveLength(1)
        expect(JSON.stringify(fallbackCalls)).not.toContain('secret-token')
        expect(JSON.stringify(fallbackCalls)).toContain('***REDACTED***')
    })

    it.each(['execute', 'executeBatched'] as const)(
        '%s falls back to the node vm as unavailable when the native addon is unavailable',
        async (path) => {
            mockHogvmNode.init.mockImplementation(() => {
                throw new Error('addon not built')
            })

            expect(await executor[path](createExampleInvocation(), [])).toBeNull()
            expect(await outcomeCount('fallback_unavailable')).toEqual(1)
            expect(await outcomeCount('fallback_exception')).toEqual(0)
        }
    )

    describe('executeBatched', () => {
        it.each(['executeRegisteredBatch', 'executeBatch'] as const)(
            'asks %s to run the batch on the native thread pool',
            async (binding) => {
                const run = async (): Promise<void> => {
                    await executor.executeBatched(createExampleInvocation(), [])
                }
                await (binding === 'executeBatch' ? withoutBinding('executeRegisteredBatch', run) : run())

                expect(mockHogvmNode[binding].mock.calls.map((call) => call[2]?.parallel)).toEqual([true])
            }
        )

        it('a marshal error means the event never executed, so it alone falls back to the node vm', async () => {
            const unrepresentable = createExampleInvocation({ bytecode: RETURN_EVENT_UUID })
            unrepresentable.state.globals.event.properties.unrepresentable = NaN
            const representable = createExampleInvocation({ bytecode: RETURN_EVENT_UUID })

            const [fellBack, executed] = await Promise.all([
                executor.executeBatched(unrepresentable, []),
                executor.executeBatched(representable, []),
            ])

            expect(fellBack).toBeNull()
            expect(executed!.execResult).toEqual(representable.state.globals.event.uuid)
            expect(await outcomeCount('fallback_exception')).toEqual(1)
        })

        it('falls back to the node vm on unsupported-program errors, same predicate as the sync path', async () => {
            const invocation = createExampleInvocation({ bytecode: CALL_MESSAGING_PREFERENCES_URL })

            expect(await executor.executeBatched(invocation, [])).toBeNull()
            expect(await outcomeCount('fallback_unsupported')).toEqual(1)
        })

        it('falls back to the node vm when the whole batch call rejects', async () => {
            mockHogvmNode.executeRegisteredBatch.mockRejectedValue(new Error('native fault'))

            expect(await executor.executeBatched(createExampleInvocation(), [])).toBeNull()
            expect(await outcomeCount('fallback_exception')).toEqual(1)
        })

        it('falls back to the node vm when registering the program throws during dispatch', async () => {
            mockHogvmNode.registerProgram.mockImplementation(() => {
                throw new Error('addon panicked')
            })

            expect(await executor.executeBatched(createExampleInvocation(), [])).toBeNull()
            expect(await outcomeCount('fallback_exception')).toEqual(1)
        })
    })

    describe('registered programs', () => {
        it('registers identical bytecode once and shares the handle across events and hog functions', async () => {
            const first = executor.execute(createExampleInvocation({ id: 'fn-1', bytecode: program(1) }), [])
            const second = executor.execute(createExampleInvocation({ id: 'fn-2', bytecode: program(1) }), [])

            expect([first!.execResult, second!.execResult]).toEqual([1, 1])
            expect(await registrationCount()).toEqual(1)
            expect(liveHandles.size).toEqual(1)
        })

        it('registers edited bytecode as a new program instead of reusing the handle of the old one', () => {
            executor.execute(createExampleInvocation({ id: 'fn-1', bytecode: program(1) }), [])
            const edited = executor.execute(createExampleInvocation({ id: 'fn-1', bytecode: program(2) }), [])

            expect(edited!.execResult).toEqual(2)
        })

        it('releases the evicted program once the cache is full, and every cached program keeps running its own bytecode', async () => {
            const values = Array.from({ length: MAX_REGISTERED_PROGRAMS + 1 }, (_, i) => i)
            for (const value of values) {
                executor.execute(createExampleInvocation({ bytecode: program(value) }), [])
            }

            expect(liveHandles.size).toEqual(MAX_REGISTERED_PROGRAMS)

            const cached = values.slice(1)
            const results = cached.map((value) =>
                executor.execute(createExampleInvocation({ bytecode: program(value) }), [])
            )
            expect(results.map((result) => result!.error ?? result!.execResult)).toEqual(cached)
            expect(await registrationCount()).toEqual(MAX_REGISTERED_PROGRAMS + 1)
        })

        it('evicts the least recently used program, keeping a hot one registered', async () => {
            const hot = createExampleInvocation({ bytecode: program(1) })
            for (let i = 1; i <= MAX_REGISTERED_PROGRAMS; i++) {
                executor.execute(createExampleInvocation({ bytecode: program(i) }), [])
            }

            executor.execute(hot, [])
            executor.execute(createExampleInvocation({ bytecode: program(MAX_REGISTERED_PROGRAMS + 1) }), [])
            const registered = await registrationCount()

            expect(executor.execute(hot, [])!.execResult).toEqual(1)
            expect(await registrationCount()).toEqual(registered)
        })

        it.each(['registerProgram', 'releaseProgram', 'executeRegisteredSync'] as const)(
            'executes unregistered when the addon lacks %s instead of throwing on every invocation',
            async (binding) => {
                await withoutBinding(binding, () => {
                    const result = executor.execute(createExampleInvocation({ bytecode: COUNT_TO_20000 }), [])

                    expect(result).not.toBeNull()
                    expect(result!.error).toBeUndefined()
                    expect(result!.execResult).toEqual(20000)
                    expect(liveHandles.size).toEqual(0)
                })
            }
        )

        it('batches through executeRegisteredBatch, registering the program once across flushes', async () => {
            const invocation = createExampleInvocation({ bytecode: program(1) })

            const first = await executor.executeBatched(invocation, [])
            const second = await executor.executeBatched(invocation, [])

            expect([first!.execResult, second!.execResult]).toEqual([1, 1])
            expect(await registrationCount()).toEqual(1)
        })

        it('batch falls back to executeBatch when the addon lacks executeRegisteredBatch', async () => {
            const invocation = createExampleInvocation({ bytecode: COUNT_TO_20000 })

            await withoutBinding('executeRegisteredBatch', async () => {
                const result = await executor.executeBatched(invocation, [])

                expect(result).not.toBeNull()
                expect(result!.error).toBeUndefined()
                expect(result!.execResult).toEqual(20000)
                expect(liveHandles.size).toEqual(0)
            })
        })
    })
})
