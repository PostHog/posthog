import { ClickHouseClient, createClient as createClickhouseClient } from '@clickhouse/client'

import { withSpan } from '~/common/tracing/tracing-utils'

import { PluginsServerConfig } from '../../types'
import { logger } from '../logger'
import { timeoutGuard } from './utils'

/**
 * Configuration for a ClickHouse connection.
 * Consumers should build this config inline where they create ClickHouse connections,
 * rather than relying on centralized builder functions.
 */
export interface ClickHouseConnectionConfig {
    url: string
    username?: string
    password?: string
    database?: string
    request_timeout?: number
    max_open_connections?: number
    keep_alive_enabled?: boolean
}

function createClickHouseClient(config: ClickHouseConnectionConfig): ClickHouseClient {
    return createClickhouseClient({
        url: config.url,
        username: config.username,
        password: config.password,
        database: config.database,
        request_timeout: config.request_timeout ?? 30000,
        max_open_connections: config.max_open_connections ?? 50,
        keep_alive: {
            enabled: config.keep_alive_enabled ?? true,
            idle_socket_ttl: 30000,
        },
    })
}

export class ClickHouseRouter {
    private client: ClickHouseClient | null = null

    constructor(private hub: PluginsServerConfig) {}

    initialize(): void {
        if (this.client) {
            return
        }

        const CLICKHOUSE_HOST = this.hub.CLICKHOUSE_HOST ?? 'localhost'
        const CLICKHOUSE_PORT = this.hub.CLICKHOUSE_PORT ?? '8123'
        const CLICKHOUSE_USERNAME = this.hub.CLICKHOUSE_USERNAME ?? 'default'
        const CLICKHOUSE_PASSWORD = this.hub.CLICKHOUSE_PASSWORD ?? ''
        const CLICKHOUSE_DATABASE = this.hub.CLICKHOUSE_DATABASE ?? 'default'
        logger.info('🤔', 'Connecting to ClickHouse...')

        this.client = createClickHouseClient({
            url: `http://${CLICKHOUSE_HOST}:${CLICKHOUSE_PORT}`,
            username: CLICKHOUSE_USERNAME,
            password: CLICKHOUSE_PASSWORD,
            database: CLICKHOUSE_DATABASE,
            request_timeout: 30000,
            max_open_connections: 50,
            keep_alive_enabled: true,
        })

        logger.info('👍', 'ClickHouse ready')
    }

    public async query<T>(query: string, tag: string = 'unknown'): Promise<T[]> {
        if (!this.client) {
            throw new Error('ClickHouse client not initialized. Call initialize() first.')
        }

        return withSpan('clickhouse', 'query.clickhouse', { tag }, async () => {
            const timeout = timeoutGuard('ClickHouse slow query warning after 30 sec', { query })

            try {
                const queryResult = await this.client!.query({
                    query,
                    format: 'JSON',
                })

                const jsonData = (await queryResult.json()).data as T[]
                return jsonData
            } catch (error) {
                logger.error('🔴', 'ClickHouse query error', {
                    query,
                    error,
                    stack: error instanceof Error ? error.stack : undefined,
                })
                throw error
            } finally {
                clearTimeout(timeout)
            }
        })
    }

    async close(): Promise<void> {
        if (this.client) {
            await this.client.close()
            this.client = null
        }
    }
}
