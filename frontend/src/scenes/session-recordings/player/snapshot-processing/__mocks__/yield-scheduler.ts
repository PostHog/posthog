// Mock implementation of yield-scheduler for testing
export const requestIdleCallback = (callback: (deadline: IdleDeadline) => void): number => {
    // In tests, call immediately with a fake deadline that has plenty of time
    callback({
        didTimeout: false,
        timeRemaining: () => 50,
    })
    return 0
}
