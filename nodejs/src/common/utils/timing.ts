import { timeoutGuard } from './db/utils'

export async function asyncTimeoutGuard(
    options: {
        message: string
        context?: Record<string, any>
        timeout?: number
    },
    fn: () => Promise<any>
): Promise<any> {
    const timeout = timeoutGuard(options.message, options.context, options.timeout)

    try {
        await fn()
    } finally {
        clearTimeout(timeout)
    }
}
