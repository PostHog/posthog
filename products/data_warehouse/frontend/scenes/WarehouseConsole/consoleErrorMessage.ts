/** The message to show for a failed console API call: the server's `error`, then its `detail`, then a fallback. */
export function consoleErrorMessage(error: unknown, fallback: string): string {
    const data = (error as { data?: { error?: unknown; detail?: unknown } } | null)?.data
    for (const candidate of [data?.error, data?.detail, (error as Error | null)?.message]) {
        if (typeof candidate === 'string' && candidate) {
            return candidate
        }
    }
    return fallback
}
