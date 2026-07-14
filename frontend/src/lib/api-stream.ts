import api from 'lib/api'

const INITIAL_RETRY_DELAY_MS = 1000
const MAX_RETRY_DELAY_MS = 30000

export interface StreamConnectionConfig {
    url: URL
    token: string
    onMessage: (data: string) => void
    onError?: (error: Error) => void
}

export interface StreamConnection {
    abort: () => void
}

/**
 * Long-lived SSE connection over `api.stream` with automatic reconnection.
 *
 * On error, reconnects with exponential backoff (1s doubling up to 30s); any successful message
 * resets the backoff. `abort()` tears down the in-flight request and any pending retry.
 * Transport-agnostic on the consumer side: callers only see `onMessage(data)` strings.
 */
export const createStreamConnection = (config: StreamConnectionConfig): StreamConnection => {
    const { url, token, onMessage, onError } = config

    let abortController = new AbortController()
    let retryTimeout: ReturnType<typeof setTimeout> | null = null
    let retryDelay = INITIAL_RETRY_DELAY_MS

    const connect = async (): Promise<void> => {
        await api.stream(url.toString(), {
            headers: {
                Authorization: `Bearer ${token}`,
            },
            signal: abortController.signal,
            onMessage: (event) => {
                retryDelay = INITIAL_RETRY_DELAY_MS
                onMessage(event.data)
            },
            onError: (error) => {
                onError?.(error)
                retryTimeout = setTimeout(() => {
                    abortController = new AbortController()
                    void connect()
                }, retryDelay)
                retryDelay = Math.min(retryDelay * 2, MAX_RETRY_DELAY_MS)
            },
        })
    }

    void connect()

    return {
        abort: () => {
            abortController.abort()
            if (retryTimeout) {
                clearTimeout(retryTimeout)
                retryTimeout = null
            }
        },
    }
}
