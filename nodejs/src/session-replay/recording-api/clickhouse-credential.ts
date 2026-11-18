import { readFile } from 'fs/promises'
import jwt from 'jsonwebtoken'

import { logger, serializeError } from '~/common/utils/logger'

import { ClickHousePasswordFallbackReason, RecordingApiMetrics } from './metrics'
import { RecordingApiConfig } from './types'

const TOKEN_EXPIRY_LEEWAY_SECONDS = 10

export class ClickHouseCredential {
    private lastFallbackReason: ClickHousePasswordFallbackReason | null = null

    constructor(
        private readonly username: string,
        private readonly staticPassword: string,
        private readonly tokenFile: string
    ) {}

    static fromConfig(
        config: Pick<RecordingApiConfig, 'CLICKHOUSE_USER' | 'CLICKHOUSE_PASSWORD' | 'CLICKHOUSE_PASSWORD_FILE'>
    ): ClickHouseCredential {
        return new ClickHouseCredential(
            config.CLICKHOUSE_USER,
            config.CLICKHOUSE_PASSWORD ?? '',
            config.CLICKHOUSE_PASSWORD_FILE
        )
    }

    async auth(): Promise<{ username: string; password: string }> {
        return { username: this.username, password: await this.password() }
    }

    async password(nowSeconds: number = Date.now() / 1000): Promise<string> {
        if (!this.tokenFile) {
            return this.staticPassword
        }
        const path = this.tokenFile
        let token: string
        try {
            token = (await readFile(path, 'utf8')).trim()
        } catch (error) {
            return this.fallBackToStaticPassword(
                'unreadable',
                '[RecordingApi] ClickHouse token file is not readable, using the static password',
                { path, error: serializeError(error) }
            )
        }
        if (!token) {
            return this.fallBackToStaticPassword(
                'empty',
                '[RecordingApi] ClickHouse token file is empty, using the static password',
                { path }
            )
        }
        // The kubelet stops refreshing the token of a terminating pod, and ClickHouse rejects an expired token.
        if (this.staticPassword && tokenExpired(token, nowSeconds)) {
            return this.fallBackToStaticPassword(
                'expired',
                '[RecordingApi] ClickHouse token has expired, using the static password',
                { path }
            )
        }
        this.lastFallbackReason = null
        return token
    }

    private fallBackToStaticPassword(
        reason: ClickHousePasswordFallbackReason,
        message: string,
        context: Record<string, unknown>
    ): string {
        RecordingApiMetrics.incrementClickhousePasswordFallback(reason)
        // This runs for every query and the counter counts each fallback, so warn only when the reason changes.
        if (reason !== this.lastFallbackReason) {
            logger.warn(message, context)
            this.lastFallbackReason = reason
        }
        return this.staticPassword
    }
}

function tokenExpired(token: string, nowSeconds: number): boolean {
    let exp: unknown
    try {
        exp = jwt.decode(token, { json: true })?.exp
    } catch {
        return false
    }
    return typeof exp === 'number' && nowSeconds >= exp - TOKEN_EXPIRY_LEEWAY_SECONDS
}
