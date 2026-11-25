// Fakes only Date, so code that reads the clock sees `now` while timers, ticks and I/O run for real.
export const pinDate = (now: number): void => {
    jest.useFakeTimers({
        now,
        doNotFake: [
            'hrtime',
            'nextTick',
            'performance',
            'queueMicrotask',
            'requestAnimationFrame',
            'cancelAnimationFrame',
            'requestIdleCallback',
            'cancelIdleCallback',
            'setImmediate',
            'clearImmediate',
            'setInterval',
            'clearInterval',
            'setTimeout',
            'clearTimeout',
        ],
    })
}
