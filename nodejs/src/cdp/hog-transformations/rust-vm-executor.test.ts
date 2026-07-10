import { createExampleInvocation } from '../_tests/fixtures'
import { resetHogvmNodeModuleCacheForTests } from './rust-vm'
import { RustVmExecutor } from './rust-vm-executor'

jest.mock('@posthog/hogvm-node', () => ({
    init: jest.fn(),
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

    it('executes the invocation bytecode against its globals and returns a finished result', () => {
        const invocation = createExampleInvocation({ bytecode: ['_H', 1, 38] })
        mockHogvmNode.executeSync.mockReturnValue(rustResult())

        const result = executor.execute(invocation, [])

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

        const result = executor.execute(createExampleInvocation(), [])

        expect(result!.error).toBeUndefined()
        expect(result!.execResult).toBeUndefined()
    })

    it('surfaces print() output as info logs with sensitive values redacted, plus a truncation warning', () => {
        mockHogvmNode.executeSync.mockReturnValue(
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
        mockHogvmNode.executeSync.mockReturnValue(rustResult({ logs: ['token is secret-a and secret-b'] }))

        const first = executor.execute(createExampleInvocation(), ['secret-a'])
        const second = executor.execute(createExampleInvocation(), ['secret-b'])

        expect(first!.logs[0].message).toEqual('token is ***REDACTED*** and secret-b')
        expect(second!.logs[0].message).toEqual('token is secret-a and ***REDACTED***')
    })

    it('a rust execution error becomes the result error with an error log, without falling back', () => {
        mockHogvmNode.executeSync.mockReturnValue(rustResult({ result: undefined, error: 'Division by zero' }))

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
        mockHogvmNode.executeSync.mockReturnValue(rustResult({ result: undefined, error }))

        expect(executor.execute(createExampleInvocation(), [])).toBeNull()
    })

    it('falls back to the node vm when the native addon is unavailable', () => {
        mockHogvmNode.init.mockImplementation(() => {
            throw new Error('addon not built')
        })

        expect(executor.execute(createExampleInvocation(), [])).toBeNull()
        expect(mockHogvmNode.executeSync).not.toHaveBeenCalled()
    })
})
