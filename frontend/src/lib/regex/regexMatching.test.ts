import { runInNewContext } from 'node:vm'

import { startRegexMatching } from './regexMatching'
import { REGEX_WORKER_SOURCE } from './regexWorkerSource'

class TestWorker {
    static instances: TestWorker[] = []
    onmessage: ((event: MessageEvent) => void) | null = null
    onerror: ((event: Event) => void) | null = null
    onmessageerror: ((event: Event) => void) | null = null
    terminate = jest.fn()
    postMessage = jest.fn()
    constructor() {
        TestWorker.instances.push(this)
    }
    message(data: unknown): void {
        this.onmessage?.({ data } as MessageEvent)
    }
}

describe('isolated regex matching', () => {
    const checks = [{ pattern: 'a', subject: 'a' }]
    beforeEach(() => {
        jest.useFakeTimers()
        TestWorker.instances = []
        Object.defineProperty(globalThis, 'Worker', { configurable: true, writable: true, value: TestWorker })
        URL.createObjectURL = jest.fn(() => 'blob:regex-test')
        URL.revokeObjectURL = jest.fn()
    })
    afterEach(() => {
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it('terminates an over-budget batch and permits a fresh successful request', async () => {
        const first = startRegexMatching(checks)
        const worker = TestWorker.instances[0]
        worker.message({ type: 'ready' })
        expect(worker.postMessage).toHaveBeenCalledWith({ checks })
        jest.advanceTimersByTime(100)
        await expect(first.promise).resolves.toEqual({ status: 'error', error: 'timeout' })
        expect(worker.terminate).toHaveBeenCalledTimes(1)
        expect(worker.onmessage).toBeNull()
        expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1)
        expect(jest.getTimerCount()).toBe(0)
        const second = startRegexMatching(checks)
        TestWorker.instances[1].message({ type: 'ready' })
        TestWorker.instances[1].message({ type: 'result', results: [{ matches: true }] })
        await expect(second.promise).resolves.toEqual({ status: 'success', results: [{ matches: true }] })
        expect(TestWorker.instances[1].terminate).toHaveBeenCalledTimes(1)
        expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2)
        expect(jest.getTimerCount()).toBe(0)
    })

    it.each(['startup', 'error', 'messageerror', 'cancel', 'hidden', 'invalid-response', 'post-failure'] as const)(
        'cleans up after %s without returning a non-match',
        async (failure) => {
            const request = startRegexMatching(checks)
            const worker = TestWorker.instances[0]
            if (failure === 'startup') {
                jest.advanceTimersByTime(5000)
            }
            if (failure === 'error') {
                worker.onerror?.(new Event('error'))
            }
            if (failure === 'messageerror') {
                worker.onmessageerror?.(new Event('messageerror'))
            }
            if (failure === 'cancel') {
                request.cancel()
                request.cancel()
            }
            if (failure === 'hidden') {
                jest.spyOn(document, 'hidden', 'get').mockReturnValue(true)
                document.dispatchEvent(new Event('visibilitychange'))
            }
            if (failure === 'invalid-response') {
                worker.message({ type: 'ready' })
                worker.message({ type: 'result', results: [] })
            }
            if (failure === 'post-failure') {
                worker.postMessage.mockImplementation(() => {
                    throw new Error('Data clone failed')
                })
                worker.message({ type: 'ready' })
            }
            expect(await request.promise).toMatchObject({ status: 'error' })
            expect(worker.terminate).toHaveBeenCalledTimes(1)
            expect(worker.onmessage).toBeNull()
            expect(worker.onerror).toBeNull()
            expect(worker.onmessageerror).toBeNull()
            expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1)
            expect(jest.getTimerCount()).toBe(0)
        }
    )

    it('starts the execution budget only after readiness and rejects a result after its deadline', async () => {
        const request = startRegexMatching(checks)
        jest.advanceTimersByTime(4999)
        const worker = TestWorker.instances[0]
        worker.message({ type: 'ready' })
        jest.advanceTimersByTime(99)
        expect(worker.terminate).not.toHaveBeenCalled()
        jest.spyOn(performance, 'now').mockReturnValue(5100)
        worker.message({ type: 'result', results: [{ matches: true }] })
        expect(await request.promise).toEqual({ status: 'error', error: 'timeout' })
        expect(worker.terminate).toHaveBeenCalledTimes(1)
    })

    it.each(['unsupported', 'csp'] as const)('reports %s as unavailable', async (failure) => {
        globalThis.Worker = (failure === 'unsupported'
            ? undefined
            : class {
                  constructor() {
                      throw new Error('CSP')
                  }
              }) as unknown as typeof Worker
        expect(await startRegexMatching(checks).promise).toEqual({ status: 'error', error: 'unavailable' })
        expect(jest.getTimerCount()).toBe(0)
        if (failure === 'csp') {
            expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1)
        }
    })

    it('executes the shipped fixed source with ordered native syntax and fresh lastIndex', () => {
        const scope = { postMessage: jest.fn(), onmessage: null as unknown as (event: { data: unknown }) => void }
        runInNewContext(REGEX_WORKER_SOURCE, { self: scope }, { timeout: 1000 })
        expect(scope.postMessage).toHaveBeenCalledWith({ type: 'ready' })
        scope.onmessage({
            data: {
                checks: [
                    { pattern: '(?<=foo)(bar)\\1', subject: 'foobarbar' },
                    { pattern: '^\\p{Letter}+$', flags: 'u', subject: 'é日' },
                    { pattern: '^hello$', flags: 'i', subject: 'HELLO' },
                    { pattern: 'a', flags: 'g', subject: 'a' },
                    { pattern: 'a', flags: 'g', subject: 'a' },
                    { pattern: 'a', flags: 'y', subject: 'ba' },
                    { pattern: '(', subject: 'x' },
                    { pattern: 'x', flags: 'invalid', subject: 'x' },
                ],
            },
        })
        expect(scope.postMessage).toHaveBeenLastCalledWith({
            type: 'result',
            results: [
                { matches: true },
                { matches: true },
                { matches: true },
                { matches: true },
                { matches: true },
                { matches: false },
                { error: 'syntax_error' },
                { error: 'syntax_error' },
            ],
        })
    })
})
