import { promiseResolveReject } from 'lib/utils'

class PromiseMutexItem<T> {
    _debugTag?: string
    _queue: PromiseMutex
    _runFn: () => Promise<void>
    _abortController: AbortController
    _priority: number = Infinity
    _resolve: (value: T) => void
    _reject: (reason?: any) => void
    _promise: Promise<T>
    constructor(
        queue: PromiseMutex,
        userFn: () => Promise<T>,
        abortController: AbortController,
        priority: number = Infinity,
        debugTag: string | undefined
    ) {
        this._debugTag = debugTag
        this._queue = queue
        this._abortController = abortController
        this._priority = priority
        const { promise, resolve, reject } = promiseResolveReject<T>()
        this._promise = promise
        this._resolve = resolve
        this._reject = reject
        this._runFn = async () => {
            if (abortController.signal.aborted) {
                reject(new FakeAbortError(abortController.signal.reason || 'AbortError'))
                return
            }
            if (this._queue._current !== null) {
                throw new Error('Developer Error: PromiseMutexItem: _runFn called while already running')
            }
            try {
                this._queue._current = this
                const result = await userFn()
                resolve(result)
            } catch (error) {
                reject(error)
            }
        }
        abortController.signal.addEventListener('abort', () => {
            reject(new FakeAbortError(abortController.signal.reason || 'AbortError'))
        })
        promise
            .catch(() => {
                // ignore
            })
            .finally(() => {
                if (this._queue._current === this) {
                    this._queue._current = null
                    this._queue._runNext()
                }
            })
    }
}

export class PromiseMutex {
    _current: PromiseMutexItem<any> | null = null
    _queue: PromiseMutexItem<any>[] = []

    /**
     * Run a function with a mutex. If the mutex is already running, the function will be queued and run when the mutex
     * is available.
     * @param fn The function to run
     * @param priority The priority of the function. Lower numbers will be run first. Defaults to Infinity.
     * @param abortController An AbortController that, if aborted,  will reject the promise and immediately start the next item in the queue.
     * @param debugTag
     */
    run = <T>({
        fn,
        priority,
        abortController,
        debugTag,
    }: {
        fn: () => Promise<T>
        priority?: number
        abortController: AbortController
        debugTag?: string
    }): Promise<T> => {
        const item = new PromiseMutexItem(this, fn, abortController, priority, debugTag)

        this._queue.push(item)
        if (this._current === null) {
            this._runNext()
        }

        return item._promise
    }

    _runNext(): void {
        this._queue.sort((a, b) => a._priority - b._priority)
        const next = this._queue.shift()
        if (next) {
            next._runFn()
                .catch(() => {
                    // ignore
                })
                .finally(() => {
                    this._tryRunNext()
                })
        }
    }

    _tryRunNext(): void {
        if (this._current === null) {
            this._runNext()
        }
    }
}

// Create a fake AbortError that allows us to use e.name === 'AbortError' to check if an error is an AbortError
class FakeAbortError extends Error {
    name = 'AbortError'
}
