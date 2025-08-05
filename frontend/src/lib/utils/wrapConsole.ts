/* oxlint-disable no-console */
export function wrapConsole(level: 'log' | 'warn' | 'error', fn: (args: Array<unknown>) => boolean): () => void {
    // Flag the handler to prevent max call stack errors (any code in this execution might retrigger the log)
    const wrappedFn = console[level]
    let inWrap = false

    console[level] = function (...args: Array<unknown>) {
        try {
            if (inWrap) {
                wrappedFn(...args)
                return
            }
            inWrap = true

            if (fn(args)) {
                wrappedFn(...args)
            }
        } finally {
            inWrap = false
        }
    }

    return () => {
        console[level] = wrappedFn
    }
}
/* oxlint-enable no-console */
