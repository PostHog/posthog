import { promiseResolveReject } from 'lib/utils'

class ParallelismControllerItem<T> {
    _debugTag?: string
    _runFn: () => Promise<void>
    _priority: number = Infinity
    _promise: Promise<T>
    constructor(
        parallelismController: ParallelismController,
        userFn: () => Promise<T>,
        abortController: AbortController,
        priority: number = Infinity,
        debugTag: string | undefined
    ) {
        this._debugTag = debugTag
        this._priority = priority
        const { promise, resolve, reject } = promiseResolveReject<T>()
        this._promise = promise
        this._runFn = async () => {
            if (abortController.signal.aborted) {
                reject(new FakeAbortError(abortController.signal.reason || 'AbortError'))
                return
            }
            if (parallelismController._current.length >= parallelismController._concurrencyLimit) {
                throw new Error('Developer Error: ParallelismControllerItem: _runFn called while already running')
            }
            try {
                parallelismController._current.push(this)
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
                if (parallelismController._current.includes(this)) {
                    parallelismController._current = parallelismController._current.filter((item) => item !== this)
                    parallelismController._runNext()
                }
            })
    }
}

export class ParallelismController {
    _concurrencyLimit: number

    _current: ParallelismControllerItem<any>[] = []
    private _queue: ParallelismControllerItem<any>[] = []

    constructor(concurrencyLimit: number) {
        this._concurrencyLimit = concurrencyLimit
    }

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
        const item = new ParallelismControllerItem(this, fn, abortController, priority, debugTag)

        this._queue.push(item)

        this._tryRunNext()

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
        if (this._current.length < this._concurrencyLimit) {
            this._runNext()
        }
    }

    setConcurrencyLimit = (limit: number): void => {
        this._concurrencyLimit = limit
    }
}

// Create a fake AbortError that allows us to use e.name === 'AbortError' to check if an error is an AbortError
class FakeAbortError extends Error {
    name = 'AbortError'
}
