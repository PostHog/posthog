type IdleCallbackHandle = number | ReturnType<typeof setTimeout>

const requestIdleCallbackAvailable = !!window?.requestIdleCallback

export const requestIdleCallback = (
    callback: (deadline: IdleDeadline) => void,
    options?: { timeout?: number }
): IdleCallbackHandle => {
    // safari does not have requestIdleCallback implemented
    if (requestIdleCallbackAvailable) {
        return window.requestIdleCallback(callback, {
            // we specify a timeout to ensure the callback gets called eventually
            timeout: options?.timeout ?? 150,
        })
    }
    const start = Date.now()
    return setTimeout(() => {
        callback({
            didTimeout: false,
            timeRemaining: () => Math.max(0, 50 - (Date.now() - start)),
        })
    }, 1)
}
