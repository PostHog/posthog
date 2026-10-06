import { logger } from '~/common/utils/logger'

import { createExampleInvocation } from '../_tests/fixtures'
import { resetHogvmNodeModuleCacheForTests } from './rust-vm'
import { MAX_REGISTERED_PROGRAMS, RustVmExecutor } from './rust-vm-executor'

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

const rustResult = (overrides: Partial<ReturnType<typeof mockHogvmNode.executeSync>> = {}) => ({
    result: { properties: { a: 1 } },
    durationUs: 1500,
    logs: [],
    logsTruncated: false,
    ...overrides,
})

// Distinct bytecode per value: "_H" header, version 1, push int, RETURN.
const program = (value: number): unknown[] => ['_H', 1, 33, value, 38]

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
    let nextHandle = 0

    beforeEach(() => {
        jest.clearAllMocks()
        resetHogvmNodeModuleCacheForTests()
        executor = new RustVmExecutor({ mmdbPath: '/dev/null' })
        // `clearAllMocks` resets call data but not implementations, so a case that makes a mock
        // throw would leak into every case after it. Re-establish the working defaults here.
        nextHandle = 0
        mockHogvmNode.init.mockImplementation(() => {})
        mockHogvmNode.registerProgram.mockImplementation(() => nextHandle++)
        mockHogvmNode.executeRegisteredSync.mockReturnValue(rustResult())
        mockHogvmNode.executeSync.mockReturnValue(rustResult())
        mockHogvmNode.executeRegisteredBatch.mockImplementation((_handle, events) =>
            Promise.resolve(events.map(() => rustResult()))
        )
        mockHogvmNode.executeBatch.mockImplementation((_bytecode, events) =>
            Promise.resolve(events.map(() => rustResult()))
        )
    })

    it('registers the invocation bytecode, executes it by handle against the globals and returns a finished result', () => {
        const invocation = createExampleInvocation({ bytecode: ['_H', 1, 38] })

        const result = executor.execute(invocation, [])

        expect(mockHogvmNode.registerProgram).toHaveBeenCalledWith(['_H', 1, 38])
        expect(mockHogvmNode.executeRegisteredSync).toHaveBeenCalledWith(0, invocation.state.globals, {
            maxSteps: 1_000_000,
        })
        expect(mockHogvmNode.executeSync).not.toHaveBeenCalled()
        expect(result).not.toBeNull()
        expect(result!.finished).toEqual(true)
        expect(result!.error).toBeUndefined()
        expect(result!.execResult).toEqual({ properties: { a: 1 } })
        expect(result!.invocation.state.timings).toEqual([{ kind: 'hog', duration_ms: 1.5 }])
        expect(result!.logs.map((log) => log.message)).toEqual(['Function completed in 1.5ms.'])
    })

    it('a null program result leaves execResult unset so the transformer drops the event', () => {
        mockHogvmNode.executeRegisteredSync.mockReturnValue(rustResult({ result: null }))

        const result = executor.execute(createExampleInvocation(), [])

        expect(result!.error).toBeUndefined()
        expect(result!.execResult).toBeUndefined()
    })

    it('surfaces print() output as info logs with sensitive values redacted, plus a truncation warning', () => {
        mockHogvmNode.executeRegisteredSync.mockReturnValue(
            rustResult({ logs: ['token is secret-token', 'plain'], logsTruncated: true })
        )

        const result = executor.execute(createExampleInvocation(), ['secret-token'])

        expect(result!.logs.map((log) => [log.level, log.message])).toEqual([
            ['info', 'token is ***REDACTED***'],
            ['info', 'plain'],
            ['warn', expect.stringContaining('Function exceeded maximum log entries')],
            ['debug', expect.stringContaining('Function completed in')],
        ])
    })

    it("redacts each invocation's logs with its own sensitive values, not another invocation's", () => {
        mockHogvmNode.executeRegisteredSync.mockReturnValue(rustResult({ logs: ['token is secret-a and secret-b'] }))

        const first = executor.execute(createExampleInvocation(), ['secret-a'])
        const second = executor.execute(createExampleInvocation(), ['secret-b'])

        expect(first!.logs[0].message).toEqual('token is ***REDACTED*** and secret-b')
        expect(second!.logs[0].message).toEqual('token is secret-a and ***REDACTED***')
    })

    it('a rust execution error becomes the result error with an error log, without falling back', () => {
        mockHogvmNode.executeRegisteredSync.mockReturnValue(
            rustResult({ result: undefined, error: 'Division by zero' })
        )

        const result = executor.execute(createExampleInvocation(), [])

        expect(result).not.toBeNull()
        expect(result!.error).toEqual('Division by zero')
        expect(result!.finished).toEqual(true)
        expect(result!.execResult).toBeUndefined()
        expect(result!.logs.map((log) => log.level)).toEqual(['error'])
        expect(result!.logs[0].message).toContain('Division by zero')
    })

    it.each([
        ['unsupported host function', 'Native call failed: unsupported_ext_fn:geoipLookup'],
        ['function missing from the rust vm', 'Unknown function sendEmail'],
        ['global chain the rust vm cannot resolve', 'Unknown Global ["inputs", "foo"]'],
    ])('falls back to the node vm on %s', (_name, error) => {
        mockHogvmNode.executeRegisteredSync.mockReturnValue(rustResult({ result: undefined, error }))

        expect(executor.execute(createExampleInvocation(), [])).toBeNull()
    })

    it('falls back to the node vm when the ffi boundary throws instead of returning an error', () => {
        // e.g. globals containing NaN/Infinity, which serde_json can't represent.
        mockHogvmNode.executeRegisteredSync.mockImplementation(() => {
            throw new Error('Failed to convert js number to serde_json::Number')
        })

        expect(executor.execute(createExampleInvocation(), [])).toBeNull()
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

    it('falls back to the node vm when the native addon is unavailable', () => {
        mockHogvmNode.init.mockImplementation(() => {
            throw new Error('addon not built')
        })

        expect(executor.execute(createExampleInvocation(), [])).toBeNull()
        expect(mockHogvmNode.registerProgram).not.toHaveBeenCalled()
        expect(mockHogvmNode.executeRegisteredSync).not.toHaveBeenCalled()
    })

    describe('executeBatched', () => {
        it('runs the invocation through executeRegisteredBatch off the JS thread and maps the result like the sync path', async () => {
            const invocation = createExampleInvocation({ bytecode: ['_H', 1, 38] })

            const result = await executor.executeBatched(invocation, [])

            expect(mockHogvmNode.registerProgram).toHaveBeenCalledWith(['_H', 1, 38])
            expect(mockHogvmNode.executeRegisteredBatch).toHaveBeenCalledWith(0, [invocation.state.globals], {
                parallel: true,
                maxSteps: 1_000_000,
            })
            expect(mockHogvmNode.executeBatch).not.toHaveBeenCalled()
            expect(result!.finished).toEqual(true)
            expect(result!.execResult).toEqual({ properties: { a: 1 } })
            expect(result!.invocation.state.timings).toEqual([{ kind: 'hog', duration_ms: 1.5 }])
        })

        it('a marshal error means the event never executed, so it alone falls back to the node vm', async () => {
            mockHogvmNode.executeRegisteredBatch.mockResolvedValue([
                rustResult({ result: undefined, error: 'marshal_error:Failed to convert js number' }),
            ])

            expect(await executor.executeBatched(createExampleInvocation(), [])).toBeNull()
            expect(mockHogvmNode.executeRegisteredBatch).toHaveBeenCalledTimes(1)
        })

        it('falls back to the node vm on unsupported-program errors, same predicate as the sync path', async () => {
            mockHogvmNode.executeRegisteredBatch.mockResolvedValue([
                rustResult({ result: undefined, error: 'Native call failed: unsupported_ext_fn:geoipLookup' }),
            ])

            expect(await executor.executeBatched(createExampleInvocation(), [])).toBeNull()
        })

        it('falls back to the node vm when the whole batch call rejects', async () => {
            mockHogvmNode.executeRegisteredBatch.mockRejectedValue(new Error('native fault'))

            expect(await executor.executeBatched(createExampleInvocation(), [])).toBeNull()
        })

        it('falls back to the node vm when registering the program throws during dispatch', async () => {
            mockHogvmNode.registerProgram.mockImplementation(() => {
                throw new Error('addon panicked')
            })

            expect(await executor.executeBatched(createExampleInvocation(), [])).toBeNull()
            expect(mockHogvmNode.executeRegisteredBatch).not.toHaveBeenCalled()
        })

        it('falls back to the node vm when the native addon is unavailable, without enqueueing', async () => {
            mockHogvmNode.init.mockImplementation(() => {
                throw new Error('addon not built')
            })

            expect(await executor.executeBatched(createExampleInvocation(), [])).toBeNull()
            expect(mockHogvmNode.executeRegisteredBatch).not.toHaveBeenCalled()
            expect(mockHogvmNode.executeBatch).not.toHaveBeenCalled()
        })
    })

    describe('registered programs', () => {
        it('registers identical bytecode once and shares the handle across events and hog functions', () => {
            executor.execute(createExampleInvocation({ id: 'fn-1', bytecode: program(1) }), [])
            executor.execute(createExampleInvocation({ id: 'fn-2', bytecode: program(1) }), [])

            expect(mockHogvmNode.registerProgram).toHaveBeenCalledTimes(1)
            expect(mockHogvmNode.executeRegisteredSync.mock.calls.map((call) => call[0])).toEqual([0, 0])
        })

        it('registers edited bytecode as a new program instead of reusing the handle of the old one', () => {
            executor.execute(createExampleInvocation({ id: 'fn-1', bytecode: program(1) }), [])
            executor.execute(createExampleInvocation({ id: 'fn-1', bytecode: program(2) }), [])

            expect(mockHogvmNode.registerProgram).toHaveBeenCalledTimes(2)
            expect(mockHogvmNode.executeRegisteredSync).toHaveBeenLastCalledWith(1, expect.anything(), {
                maxSteps: 1_000_000,
            })
        })

        it('releases a handle once the cache is full so the rust registry stays bounded', () => {
            for (let i = 0; i < MAX_REGISTERED_PROGRAMS; i++) {
                executor.execute(createExampleInvocation({ bytecode: program(i) }), [])
            }
            expect(mockHogvmNode.releaseProgram).not.toHaveBeenCalled()

            executor.execute(createExampleInvocation({ bytecode: program(MAX_REGISTERED_PROGRAMS) }), [])

            expect(mockHogvmNode.releaseProgram).toHaveBeenCalledTimes(1)
        })

        it('evicts the least recently used program, keeping a hot one registered', () => {
            const hot = createExampleInvocation({ bytecode: program(0) })
            for (let i = 0; i < MAX_REGISTERED_PROGRAMS; i++) {
                executor.execute(createExampleInvocation({ bytecode: program(i) }), [])
            }
            const hotHandle = mockHogvmNode.executeRegisteredSync.mock.calls[0][0]

            executor.execute(hot, [])
            executor.execute(createExampleInvocation({ bytecode: program(MAX_REGISTERED_PROGRAMS) }), [])

            expect(mockHogvmNode.releaseProgram).toHaveBeenCalledTimes(1)
            expect(mockHogvmNode.releaseProgram).not.toHaveBeenCalledWith(hotHandle)

            mockHogvmNode.registerProgram.mockClear()
            executor.execute(hot, [])
            expect(mockHogvmNode.registerProgram).not.toHaveBeenCalled()
            expect(mockHogvmNode.executeRegisteredSync).toHaveBeenLastCalledWith(hotHandle, expect.anything(), {
                maxSteps: 1_000_000,
            })
        })

        it.each(['registerProgram', 'releaseProgram', 'executeRegisteredSync'] as const)(
            'executes unregistered when the addon lacks %s instead of throwing on every invocation',
            async (binding) => {
                await withoutBinding(binding, () => {
                    const result = executor.execute(createExampleInvocation({ bytecode: program(1) }), [])

                    expect(result).not.toBeNull()
                    expect(result!.error).toBeUndefined()
                    expect(mockHogvmNode.executeSync).toHaveBeenCalledTimes(1)
                    expect(nextHandle).toEqual(0)
                })
            }
        )

        it('batches through executeRegisteredBatch, registering the program once across flushes', async () => {
            const invocation = createExampleInvocation({ bytecode: program(1) })

            const first = await executor.executeBatched(invocation, [])
            const second = await executor.executeBatched(invocation, [])

            expect(mockHogvmNode.registerProgram).toHaveBeenCalledTimes(1)
            expect(mockHogvmNode.executeRegisteredBatch).toHaveBeenCalledTimes(2)
            expect(mockHogvmNode.executeRegisteredBatch).toHaveBeenLastCalledWith(0, [invocation.state.globals], {
                parallel: true,
                maxSteps: 1_000_000,
            })
            expect(first!.error).toBeUndefined()
            expect(second!.error).toBeUndefined()
        })

        it('batch falls back to executeBatch when the addon lacks executeRegisteredBatch', async () => {
            const invocation = createExampleInvocation({ bytecode: program(1) })

            await withoutBinding('executeRegisteredBatch', async () => {
                const result = await executor.executeBatched(invocation, [])

                expect(result).not.toBeNull()
                expect(result!.error).toBeUndefined()
                expect(mockHogvmNode.registerProgram).not.toHaveBeenCalled()
                expect(mockHogvmNode.executeBatch).toHaveBeenCalledWith(
                    invocation.hogFunction.bytecode,
                    [invocation.state.globals],
                    { parallel: true, maxSteps: 1_000_000 }
                )
            })
        })
    })
})
