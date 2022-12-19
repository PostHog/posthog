export function killProcess(): void {
    // In tests, only call SIGTERM once to avoid leaky tests.
    // In production, kill two more times if the first one fails.
    setTimeout(() => process.kill(process.pid, 'SIGTERM'), 100)
    if (process.env.NODE_ENV !== 'test') {
        setTimeout(() => process.kill(process.pid, 'SIGTERM'), 60000)
        setTimeout(() => process.kill(process.pid, 'SIGKILL'), 120000)
    }
}
