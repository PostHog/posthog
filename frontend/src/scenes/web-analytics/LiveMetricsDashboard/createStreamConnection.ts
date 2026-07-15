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

export const createStreamConnection = (config: StreamConnectionConfig): StreamConnection => {
    const { url, token, onMessage, onError } = config

    let abortController = new AbortController()
    let retryTimeout: ReturnType<typeof setTimeout> | null = null
    let retryDelay = INITIAL_RETRY_DELAY_MS
    let aborted = false

    function scheduleReconnect(): void {
        if (aborted || retryTimeout) {
            return
        }
        retryTimeout = setTimeout(() => {
            retryTimeout = null
            if (aborted) {
                return
            }
            abortController = new AbortController()
            void connect()
        }, retryDelay)
        retryDelay = Math.min(retryDelay * 2, MAX_RETRY_DELAY_MS)
    }

    async function connect(): Promise<void> {
        if (aborted) {
            return
        }
        try {
            await api.stream(url.toString(), {
                headers: {
                    Authorization: `Bearer ${token}`,
                },
                signal: abortController.signal,
                onMessage: (event) => {
                    if (aborted) {
                        return
                    }
                    retryDelay = INITIAL_RETRY_DELAY_MS
                    onMessage(event.data)
                },
                onError: (error) => {
                    if (aborted) {
                        return
                    }
                    scheduleReconnect()
                    onError?.(error)
                    throw error
                },
            })
        } catch (error) {
            if (!aborted && !retryTimeout) {
                onError?.(error instanceof Error ? error : new Error(String(error)))
                scheduleReconnect()
            }
        }
    }

    void connect()

    return {
        abort: () => {
            aborted = true
            abortController.abort()
            if (retryTimeout) {
                clearTimeout(retryTimeout)
                retryTimeout = null
            }
        },
    }
}
