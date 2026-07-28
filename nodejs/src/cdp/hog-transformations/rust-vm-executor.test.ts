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
    let nextHandle = 0

    beforeEach(() => {
        jest.clearAllMocks()
        resetHogvmNodeModuleCacheForTests()
        executor = new RustVmExecutor({ mmdbPath: '/dev/null' })
        // Fixtures without an `updated_at` take the unregistered `executeSync` path; the
        // registered path has its own cases below. Handles restart at 0 per test so cases that
        // assert on a specific handle don't depend on how many ran before them.
        nextHandle = 0
        mockHogvmNode.registerProgram.mockImplementation(() => nextHandle++)
        mockHogvmNode.executeRegisteredSync.mockReturnValue(rustResult())
        // `clearMocks` only clears call data, not implementations, so a case that makes `init` or
        // `executeSync` throw would otherwise leak into every case declared after it. Re-establish
        // the working defaults here; the cases that need failures still install their own.
        mockHogvmNode.init.mockImplementation(() => {})
        mockHogvmNode.executeSync.mockReturnValue(rustResult())
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

    it('falls back to the node vm when the ffi boundary throws instead of returning an error', () => {
        // e.g. globals containing NaN/Infinity, which serde_json can't represent.
        mockHogvmNode.executeSync.mockImplementation(() => {
            throw new Error('Failed to convert js number to serde_json::Number')
        })

        expect(executor.execute(createExampleInvocation(), [])).toBeNull()
    })

    it('redacts sensitive values from fallback logs', () => {
        // Marshalling errors and panic messages can embed values from the invocation globals.
        const warnSpy = jest.spyOn(logger, 'warn').mockImplementation(() => {})
        mockHogvmNode.executeSync.mockImplementation(() => {
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

            const result = await executor.executeBatched(invocation, [])

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

            expect(await executor.executeBatched(createExampleInvocation(), [])).toBeNull()
            expect(mockHogvmNode.executeBatch).toHaveBeenCalledTimes(1)
        })

        it('falls back to the node vm on unsupported-program errors, same predicate as the sync path', async () => {
            mockHogvmNode.executeBatch.mockResolvedValue([
                rustResult({ result: undefined, error: 'Native call failed: unsupported_ext_fn:geoipLookup' }),
            ])

            expect(await executor.executeBatched(createExampleInvocation(), [])).toBeNull()
        })

        it('falls back to the node vm when the whole batch call rejects', async () => {
            mockHogvmNode.executeBatch.mockRejectedValue(new Error('native fault'))

            expect(await executor.executeBatched(createExampleInvocation(), [])).toBeNull()
        })

        it('falls back to the node vm when the native addon is unavailable, without enqueueing', async () => {
            mockHogvmNode.init.mockImplementation(() => {
                throw new Error('addon not built')
            })

            expect(await executor.executeBatched(createExampleInvocation(), [])).toBeNull()
            expect(mockHogvmNode.executeBatch).not.toHaveBeenCalled()
        })
    })

    describe('registered programs', () => {
        const versioned = (overrides: { id?: string; updated_at?: string; bytecode?: any[] } = {}) =>
            createExampleInvocation({
                id: 'fn-1',
                updated_at: '2026-01-01T00:00:00Z',
                bytecode: ['_H', 1, 38],
                ...overrides,
            })

        it('registers a versioned program once and reuses the handle across events', () => {
            // The whole point of the registry: without the cache every event re-marshals and
            // re-decodes the bytecode across the napi boundary.
            const first = executor.execute(versioned(), [])
            const second = executor.execute(versioned(), [])

            expect(mockHogvmNode.registerProgram).toHaveBeenCalledTimes(1)
            expect(mockHogvmNode.executeSync).not.toHaveBeenCalled()
            expect(mockHogvmNode.executeRegisteredSync).toHaveBeenCalledTimes(2)
            expect(mockHogvmNode.executeRegisteredSync.mock.calls.map((call) => call[0])).toEqual([0, 0])
            expect(first!.error).toBeUndefined()
            expect(second!.error).toBeUndefined()
        })

        it('re-registers and releases the old handle when the function is edited', () => {
            // A cache keyed on id alone would keep running the pre-edit bytecode forever.
            executor.execute(versioned(), [])
            executor.execute(versioned({ updated_at: '2026-02-02T00:00:00Z' }), [])

            expect(mockHogvmNode.registerProgram).toHaveBeenCalledTimes(2)
            expect(mockHogvmNode.releaseProgram).toHaveBeenCalledWith(0)
            expect(mockHogvmNode.executeRegisteredSync).toHaveBeenLastCalledWith(1, expect.anything(), {
                maxSteps: 1_000_000,
            })
        })

        it('releases a handle once the cache is full so the rust registry stays bounded', () => {
            for (let i = 0; i < MAX_REGISTERED_PROGRAMS; i++) {
                executor.execute(versioned({ id: `fn-${i}` }), [])
            }
            expect(mockHogvmNode.releaseProgram).not.toHaveBeenCalled()

            executor.execute(versioned({ id: 'one-too-many' }), [])

            expect(mockHogvmNode.releaseProgram).toHaveBeenCalledTimes(1)
        })

        it('evicts the least recently used function, keeping a hot one registered', () => {
            // Evicting by registration order instead would drop the function that runs on every
            // event just because it was registered first, then re-register and re-evict it in a
            // loop for as long as the process keeps seeing new functions.
            const hot = versioned({ id: 'fn-0' })
            for (let i = 0; i < MAX_REGISTERED_PROGRAMS; i++) {
                executor.execute(versioned({ id: `fn-${i}` }), [])
            }
            const hotHandle = mockHogvmNode.executeRegisteredSync.mock.calls[0][0]

            executor.execute(hot, []) // hot is now the most recently used, fn-1 the least
            executor.execute(versioned({ id: 'one-too-many' }), [])

            expect(mockHogvmNode.releaseProgram).toHaveBeenCalledTimes(1)
            expect(mockHogvmNode.releaseProgram).not.toHaveBeenCalledWith(hotHandle)

            // ...and the hot function still executes on its original handle, with no re-registration.
            mockHogvmNode.registerProgram.mockClear()
            executor.execute(hot, [])
            expect(mockHogvmNode.registerProgram).not.toHaveBeenCalled()
            expect(mockHogvmNode.executeRegisteredSync).toHaveBeenLastCalledWith(hotHandle, expect.anything(), {
                maxSteps: 1_000_000,
            })
        })

        it('executes unregistered when the addon predates the registry bindings', () => {
            // The addon is a separately built native binary. If it lacks registerProgram we must
            // execute unregistered, not throw and fall back to the node vm on every invocation.
            const registerProgram = mockHogvmNode.registerProgram
            // @ts-expect-error - simulating an older addon build that has no registry API
            delete mockHogvmNode.registerProgram
            try {
                const result = executor.execute(versioned(), [])

                expect(result).not.toBeNull()
                expect(result!.error).toBeUndefined()
                expect(mockHogvmNode.executeSync).toHaveBeenCalledTimes(1)
                expect(mockHogvmNode.executeRegisteredSync).not.toHaveBeenCalled()
            } finally {
                mockHogvmNode.registerProgram = registerProgram
            }
        })

        it('executes unregistered when the function carries no version to key the cache by', () => {
            // Without a version key a cached handle could serve stale bytecode after an edit.
            executor.execute(versioned({ updated_at: undefined }), [])

            expect(mockHogvmNode.registerProgram).not.toHaveBeenCalled()
            expect(mockHogvmNode.executeSync).toHaveBeenCalledTimes(1)
        })
    })
})
