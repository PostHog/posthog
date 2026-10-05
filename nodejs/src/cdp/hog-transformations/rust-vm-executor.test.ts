import { logger } from '~/common/utils/logger'

import { createExampleInvocation } from '../_tests/fixtures'
import { resetHogvmNodeModuleCacheForTests } from './rust-vm'
import { RustVmExecutor } from './rust-vm-executor'

jest.mock('@posthog/hogvm-node', () => ({
    init: jest.fn(),
    executeSync: jest.fn(),
    executeBatch: jest.fn(),
}))

const mockHogvmNode = jest.mocked(jest.requireMock<typeof import('@posthog/hogvm-node')>('@posthog/hogvm-node'))

const nodeFunctions = { parseUserAgent: () => null }

const rustResult = (overrides: Partial<ReturnType<typeof mockHogvmNode.executeSync>> = {}) => ({
    result: { properties: { a: 1 } },
    durationUs: 1500,
    logs: [],
    logsTruncated: false,
    ...overrides,
})

describe('RustVmExecutor', () => {
    let executor: RustVmExecutor

    beforeEach(() => {
        jest.clearAllMocks()
        resetHogvmNodeModuleCacheForTests()
        executor = new RustVmExecutor({ mmdbPath: '/dev/null' })
    })

    it('executes the invocation bytecode against its globals and returns a finished result', () => {
        const invocation = createExampleInvocation({ bytecode: ['_H', 1, 38] })
        mockHogvmNode.executeSync.mockReturnValue(rustResult())

        const result = executor.execute(invocation, [], nodeFunctions)

        expect(mockHogvmNode.executeSync).toHaveBeenCalledWith(['_H', 1, 38], invocation.state.globals, {
            maxSteps: 1_000_000,
        })
        expect(result).not.toBeNull()
        expect(result!.finished).toEqual(true)
        expect(result!.error).toBeUndefined()
        expect(result!.execResult).toEqual({ properties: { a: 1 } })
        expect(result!.invocation.state.timings).toEqual([{ kind: 'hog', duration_ms: 1.5 }])
        expect(result!.logs.map((log) => log.message)).toEqual(['Function completed in 1.5ms.'])
    })

    it('a null program result leaves execResult unset so the transformer drops the event', () => {
        mockHogvmNode.executeSync.mockReturnValue(rustResult({ result: null }))

        const result = executor.execute(createExampleInvocation(), [], nodeFunctions)

        expect(result!.error).toBeUndefined()
        expect(result!.execResult).toBeUndefined()
    })

    it('surfaces print() output as info logs with sensitive values redacted, plus a truncation warning', () => {
        mockHogvmNode.executeSync.mockReturnValue(
            rustResult({ logs: ['token is secret-token', 'plain'], logsTruncated: true })
        )

        const result = executor.execute(createExampleInvocation(), ['secret-token'], nodeFunctions)

        expect(result!.logs.map((log) => [log.level, log.message])).toEqual([
            ['info', 'token is ***REDACTED***'],
            ['info', 'plain'],
            ['warn', expect.stringContaining('Function exceeded maximum log entries')],
            ['debug', expect.stringContaining('Function completed in')],
        ])
    })

    it("redacts each invocation's logs with its own sensitive values, not another invocation's", () => {
        mockHogvmNode.executeSync.mockReturnValue(rustResult({ logs: ['token is secret-a and secret-b'] }))

        const first = executor.execute(createExampleInvocation(), ['secret-a'], nodeFunctions)
        const second = executor.execute(createExampleInvocation(), ['secret-b'], nodeFunctions)

        expect(first!.logs[0].message).toEqual('token is ***REDACTED*** and secret-b')
        expect(second!.logs[0].message).toEqual('token is secret-a and ***REDACTED***')
    })

    it.each([
        ['a rust execution error', 'Division by zero'],
        ['a function the node vm cannot resolve either', 'Unknown function random'],
    ])('%s becomes the result error with an error log, without falling back', (_name, error) => {
        mockHogvmNode.executeSync.mockReturnValue(rustResult({ result: undefined, error }))

        const result = executor.execute(createExampleInvocation(), [], nodeFunctions)

        expect(result).not.toBeNull()
        expect(result!.error).toEqual(error)
        expect(result!.finished).toEqual(true)
        expect(result!.execResult).toBeUndefined()
        expect(result!.logs.map((log) => log.level)).toEqual(['error'])
        expect(result!.logs[0].message).toContain(error)
    })

    it.each([
        ['unsupported host function', 'Native call failed: unsupported_ext_fn:geoipLookup'],
        ['host function missing from the rust vm', 'Unknown function parseUserAgent'],
        ['stl function missing from the rust vm', 'Unknown function extract'],
        ['global chain the rust vm cannot resolve', 'Unknown Global ["inputs", "foo"]'],
    ])('falls back to the node vm on %s', (_name, error) => {
        mockHogvmNode.executeSync.mockReturnValue(rustResult({ result: undefined, error }))

        expect(executor.execute(createExampleInvocation(), [], nodeFunctions)).toBeNull()
    })

    it('logs a repeated unsupported fallback once per function and error', () => {
        const warnSpy = jest.spyOn(logger, 'warn').mockImplementation(() => {})
        mockHogvmNode.executeSync.mockReturnValue(
            rustResult({ result: undefined, error: 'Unknown function parseUserAgent' })
        )

        const invocation = createExampleInvocation({ id: 'function-a' })

        expect(executor.execute(invocation, [], nodeFunctions)).toBeNull()
        expect(executor.execute(invocation, [], nodeFunctions)).toBeNull()
        expect(executor.execute(createExampleInvocation({ id: 'function-b' }), [], nodeFunctions)).toBeNull()

        const fallbackCalls = warnSpy.mock.calls.filter((call) => String(call[1]).includes('fell back'))
        expect(fallbackCalls.map((call) => (call[2] as { functionId: string }).functionId)).toEqual([
            'function-a',
            'function-b',
        ])
    })

    it('falls back to the node vm when the ffi boundary throws instead of returning an error', () => {
        // e.g. globals containing NaN/Infinity, which serde_json can't represent.
        mockHogvmNode.executeSync.mockImplementation(() => {
            throw new Error('Failed to convert js number to serde_json::Number')
        })

        expect(executor.execute(createExampleInvocation(), [], nodeFunctions)).toBeNull()
    })

    it('redacts sensitive values from fallback logs', () => {
        // Marshalling errors and panic messages can embed values from the invocation globals.
        const warnSpy = jest.spyOn(logger, 'warn').mockImplementation(() => {})
        mockHogvmNode.executeSync.mockImplementation(() => {
            throw new Error('failed to convert value "secret-token" at inputs')
        })

        expect(executor.execute(createExampleInvocation(), ['secret-token'], nodeFunctions)).toBeNull()

        const fallbackCalls = warnSpy.mock.calls.filter((call) => String(call[1]).includes('fell back'))
        expect(fallbackCalls).toHaveLength(1)
        expect(JSON.stringify(fallbackCalls)).not.toContain('secret-token')
        expect(JSON.stringify(fallbackCalls)).toContain('***REDACTED***')
    })

    it('falls back to the node vm when the native addon is unavailable', () => {
        mockHogvmNode.init.mockImplementation(() => {
            throw new Error('addon not built')
        })

        expect(executor.execute(createExampleInvocation(), [], nodeFunctions)).toBeNull()
        expect(mockHogvmNode.executeSync).not.toHaveBeenCalled()
    })

    describe('executeBatched', () => {
        beforeEach(() => {
            // clearAllMocks doesn't clear implementations: without this, the sync-path
            // "addon unavailable" test's throwing init would leak into these tests.
            mockHogvmNode.init.mockImplementation(() => {})
        })

        it('runs the invocation through executeBatch off the JS thread and maps the result like the sync path', async () => {
            const invocation = createExampleInvocation({ bytecode: ['_H', 1, 38] })
            mockHogvmNode.executeBatch.mockResolvedValue([rustResult()])

            const result = await executor.executeBatched(invocation, [], nodeFunctions)

            expect(mockHogvmNode.executeBatch).toHaveBeenCalledWith(['_H', 1, 38], [invocation.state.globals], {
                parallel: true,
                maxSteps: 1_000_000,
            })
            expect(result!.finished).toEqual(true)
            expect(result!.execResult).toEqual({ properties: { a: 1 } })
            expect(result!.invocation.state.timings).toEqual([{ kind: 'hog', duration_ms: 1.5 }])
        })

        it('a marshal error means the event never executed, so it alone falls back to the node vm', async () => {
            mockHogvmNode.executeBatch.mockResolvedValue([
                rustResult({ result: undefined, error: 'marshal_error:Failed to convert js number' }),
            ])

            expect(await executor.executeBatched(createExampleInvocation(), [], nodeFunctions)).toBeNull()
            expect(mockHogvmNode.executeBatch).toHaveBeenCalledTimes(1)
        })

        it('falls back to the node vm on unsupported-program errors, same predicate as the sync path', async () => {
            mockHogvmNode.executeBatch.mockResolvedValue([
                rustResult({ result: undefined, error: 'Native call failed: unsupported_ext_fn:geoipLookup' }),
            ])

            expect(await executor.executeBatched(createExampleInvocation(), [], nodeFunctions)).toBeNull()
        })

        it('falls back to the node vm when the whole batch call rejects', async () => {
            mockHogvmNode.executeBatch.mockRejectedValue(new Error('native fault'))

            expect(await executor.executeBatched(createExampleInvocation(), [], nodeFunctions)).toBeNull()
        })

        it('falls back to the node vm when the native addon is unavailable, without enqueueing', async () => {
            mockHogvmNode.init.mockImplementation(() => {
                throw new Error('addon not built')
            })

            expect(await executor.executeBatched(createExampleInvocation(), [], nodeFunctions)).toBeNull()
            expect(mockHogvmNode.executeBatch).not.toHaveBeenCalled()
        })
    })
})
