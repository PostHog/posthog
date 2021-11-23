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
