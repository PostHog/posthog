import { promiseResolveReject } from 'lib/utils'

class PromiseMutexItem<T> {
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
        priority: number = Infinity
    ) {
        this._queue = queue
        this._abortController = abortController
        this._priority = priority
        const { promise, resolve, reject } = promiseResolveReject<T>()
        this._promise = promise
        this._resolve = resolve
        this._reject = reject
        this._runFn = async () => {
            if (this._abortController.signal.aborted) {
                reject(new Error('Aborted'))
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
            reject(new Error('Aborted'))
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
    private _queue: PromiseMutexItem<any>[] = []

    run = <T>({
        fn,
        priority,
        abortController,
    }: {
        fn: () => Promise<T>
        priority: number
        abortController: AbortController
    }): Promise<T> => {
        const item = new PromiseMutexItem(this, fn, abortController, priority)

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
            next._runFn().catch(() => {
                // ignore
            })
        }
    }
}
