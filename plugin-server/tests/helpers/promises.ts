interface MockPromise<T> {
    promise: Promise<T>
    resolve: (value?: any) => void
    reject: (error: any) => void
}

export function createPromise<T = void>(): MockPromise<T> {
    const result: Partial<MockPromise<T>> = {}
    result.promise = new Promise<T>((_resolve, _reject) => {
        result.resolve = _resolve
        result.reject = _reject
    })

    return result as MockPromise<T>
}

export class WaitEvent {
    private promise: Promise<void>
    private resolve: () => void

    constructor() {
        this.promise = new Promise((resolve) => {
            this.resolve = resolve
        })
    }

    public set() {
        this.resolve()
    }

    public async wait() {
        return this.promise
    }
}
