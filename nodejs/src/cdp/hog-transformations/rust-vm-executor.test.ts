import { createExampleInvocation } from '../_tests/fixtures'
import { resetHogvmNodeModuleCacheForTests } from './rust-vm'
import { RustVmExecutor } from './rust-vm-executor'

jest.mock('@posthog/hogvm-node', () => ({
    init: jest.fn(),
    executeBatch: jest.fn(),
    executeSync: jest.fn(),
}))

const mockHogvmNode = jest.mocked(jest.requireMock<typeof import('@posthog/hogvm-node')>('@posthog/hogvm-node'))

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

    it('executes the invocation bytecode against its globals off the JS thread and returns a finished result', async () => {
        const invocation = createExampleInvocation({ bytecode: ['_H', 1, 38] })
        mockHogvmNode.executeBatch.mockResolvedValue([rustResult()])

        const result = await executor.execute(invocation, [])

        // executeBatch runs as a napi AsyncTask off the event loop — the sync
        // entry point must not be used on the ingestion hot path.
        expect(mockHogvmNode.executeBatch).toHaveBeenCalledWith(['_H', 1, 38], [invocation.state.globals], {
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

    it('a null program result leaves execResult unset so the transformer drops the event', async () => {
        mockHogvmNode.executeBatch.mockResolvedValue([rustResult({ result: null })])

        const result = await executor.execute(createExampleInvocation(), [])

        expect(result!.error).toBeUndefined()
        expect(result!.execResult).toBeUndefined()
    })

    it('surfaces print() output as info logs with sensitive values redacted, plus a truncation warning', async () => {
        mockHogvmNode.executeBatch.mockResolvedValue([
            rustResult({ logs: ['token is secret-token', 'plain'], logsTruncated: true }),
        ])

        const result = await executor.execute(createExampleInvocation(), ['secret-token'])

        expect(result!.logs.map((log) => [log.level, log.message])).toEqual([
            ['info', 'token is ***REDACTED***'],
            ['info', 'plain'],
            ['warn', expect.stringContaining('Function exceeded maximum log entries')],
            ['debug', expect.stringContaining('Function completed in')],
        ])
    })

    it("redacts each invocation's logs with its own sensitive values, not another invocation's", async () => {
        mockHogvmNode.executeBatch.mockResolvedValue([rustResult({ logs: ['token is secret-a and secret-b'] })])

        const first = await executor.execute(createExampleInvocation(), ['secret-a'])
        const second = await executor.execute(createExampleInvocation(), ['secret-b'])

        expect(first!.logs[0].message).toEqual('token is ***REDACTED*** and secret-b')
        expect(second!.logs[0].message).toEqual('token is secret-a and ***REDACTED***')
    })

    it('a rust execution error becomes the result error with an error log, without falling back', async () => {
        mockHogvmNode.executeBatch.mockResolvedValue([rustResult({ result: undefined, error: 'Division by zero' })])

        const result = await executor.execute(createExampleInvocation(), [])

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
    ])('falls back to the node vm on %s', async (_name, error) => {
        mockHogvmNode.executeBatch.mockResolvedValue([rustResult({ result: undefined, error })])

        await expect(executor.execute(createExampleInvocation(), [])).resolves.toBeNull()
    })

    it('falls back to the node vm when the ffi boundary throws instead of returning an error', async () => {
        // e.g. globals containing NaN/Infinity, which serde_json can't represent.
        mockHogvmNode.executeBatch.mockRejectedValue(new Error('Failed to convert js number to serde_json::Number'))

        await expect(executor.execute(createExampleInvocation(), [])).resolves.toBeNull()
    })

    it('falls back to the node vm when the native addon is unavailable', async () => {
        mockHogvmNode.init.mockImplementation(() => {
            throw new Error('addon not built')
        })

        await expect(executor.execute(createExampleInvocation(), [])).resolves.toBeNull()
        expect(mockHogvmNode.executeBatch).not.toHaveBeenCalled()
    })
})
