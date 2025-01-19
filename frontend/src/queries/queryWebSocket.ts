import { ApiMethodOptions } from 'lib/api'

import { DashboardFilter, DataNode, HogQLVariable, RefreshType } from './schema'

export class QueryWebSocketManager {
    private socket: WebSocket | null = null
    private url: string
    private pendingQueries = new Map<
        string,
        { payload: any; resolve: (value: any) => void; reject: (reason?: any) => void }
    >()
    private idleTimeout: NodeJS.Timeout | null = null
    private idleTimeoutDuration = 20000 // 20 seconds of idle time before disconnecting

    constructor(url: string) {
        this.url = url
    }

    private connect(): void {
        if (
            this.socket &&
            (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)
        ) {
            return // Avoid redundant connections
        }

        this.socket = new WebSocket(this.url)

        this.socket.onopen = () => {
            this.resendPendingQueries()
        }

        this.socket.onmessage = (event) => {
            const response = JSON.parse(event.data)
            const { client_query_id, data, error } = response

            if (this.pendingQueries.has(client_query_id)) {
                const { resolve, reject } = this.pendingQueries.get(client_query_id)!
                this.pendingQueries.delete(client_query_id)
                if (error) {
                    reject(new Error(error))
                } else {
                    resolve(data)
                }
                this.startIdleTimeout() // Restart idle timeout after handling a message
            }
        }

        this.socket.onclose = () => {
            if (this.pendingQueries.size > 0) {
                this.connect()
            }
        }
    }

    private disconnect(): void {
        if (this.socket) {
            this.socket.close()
            this.socket = null
        }
    }

    private resendPendingQueries(): void {
        for (const [_, { payload }] of this.pendingQueries) {
            this.socket?.send(JSON.stringify(payload))
        }
    }

    private startIdleTimeout(): void {
        if (this.idleTimeout) {
            clearTimeout(this.idleTimeout)
        }
        if (this.pendingQueries.size === 0) {
            this.idleTimeout = setTimeout(() => this.disconnect(), this.idleTimeoutDuration)
        }
    }

    public sendQuery<N extends DataNode>(
        queryNode: N,
        methodOptions?: ApiMethodOptions,
        refreshParam?: RefreshType | undefined,
        queryId?: string,
        filtersOverride?: DashboardFilter | null,
        variablesOverride?: Record<string, HogQLVariable> | null
        /**
         * Whether to limit the function to just polling the provided query ID.
         * This is important in shared contexts, where we cannot create arbitrary queries via POST – we can only GET.
         */
    ): Promise<NonNullable<N['response']>> {
        const client_query_id = queryId || Math.random().toString(36).substring(2)

        const payload = {
            query: queryNode,
            methodOptions: methodOptions,
            refresh: refreshParam,
            client_query_id: client_query_id,
            filtersOverride: filtersOverride,
            variablesOverride: variablesOverride,
        }

        return new Promise((resolve, reject) => {
            this.pendingQueries.set(client_query_id, { payload, resolve, reject })

            if (!this.socket || this.socket.readyState === WebSocket.CLOSED) {
                this.connect()
            }

            if (this.socket?.readyState === WebSocket.OPEN) {
                this.socket.send(JSON.stringify(payload))
            }

            // Add a timeout for the query
            setTimeout(() => {
                if (this.pendingQueries.has(client_query_id)) {
                    this.pendingQueries.delete(client_query_id)
                    reject(new Error('Query timed out.'))
                }
            }, 600000) // 600 seconds timeout
        })
    }
}
