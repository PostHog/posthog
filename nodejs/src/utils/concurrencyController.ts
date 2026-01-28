import FastPriorityQueue from 'fastpriorityqueue'

export function promiseResolveReject<T>(): {
    resolve: (value: T) => void
    reject: (reason?: any) => void
    promise: Promise<T>
} {
    let resolve: (value: T) => void
    let reject: (reason?: any) => void
    const promise = new Promise<T>((innerResolve, innerReject) => {
        resolve = innerResolve
        reject = innerReject
    })
    return { resolve: resolve!, reject: reject!, promise }
}

// Note that this file also exists in the frontend code, please keep them in sync as the tests only exist in the other version
class ConcurrencyControllerItem<T> {
    _debugTag?: string
    _runFn: () => Promise<void>
    _priority: number = Infinity
    _promise: Promise<T>
    constructor(
        concurrencyController: ConcurrencyController,
        userFn: () => Promise<T>,
        abortController: AbortController | undefined,
        priority: number = Infinity,
        debugTag: string | undefined
    ) {
        this._debugTag = debugTag
        this._priority = priority
        const { promise, resolve, reject } = promiseResolveReject<T>()
        this._promise = promise
        this._runFn = async () => {
            if (abortController?.signal.aborted) {
                reject(new FakeAbortError(abortController.signal.reason || 'AbortError'))
                return
            }
            if (concurrencyController._current.length >= concurrencyController._concurrencyLimit) {
                throw new Error('Developer Error: ConcurrencyControllerItem: _runFn called while already running')
            }
            try {
                concurrencyController._current.push(this)
                const result = await userFn()
                resolve(result)
            } catch (error) {
                reject(error)
            }
        }
        abortController?.signal.addEventListener('abort', () => {
            reject(new FakeAbortError(abortController.signal.reason || 'AbortError'))
        })
        promise
            .catch(() => {
                // ignore
            })
            .finally(() => {
                if (concurrencyController._current.includes(this)) {
                    concurrencyController._current = concurrencyController._current.filter((item) => item !== this)
                    concurrencyController._runNext()
                }
            })
    }
}

export class ConcurrencyController {
    _concurrencyLimit: number

    _current: ConcurrencyControllerItem<any>[] = []
    private _queue: FastPriorityQueue<ConcurrencyControllerItem<any>> = new FastPriorityQueue(
        (a, b) => a._priority < b._priority
    )

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
        abortController?: AbortController
        debugTag?: string
    }): Promise<T> => {
        const item = new ConcurrencyControllerItem(this, fn, abortController, priority, debugTag)

        this._queue.add(item)

        this._tryRunNext()

        return item._promise
    }

    _runNext(): void {
        const next = this._queue.poll()
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
