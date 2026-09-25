import { readFile } from 'fs/promises'
import jwt from 'jsonwebtoken'

import { logger, serializeError } from '~/common/utils/logger'

import { RecordingApiMetrics } from './metrics'
import { RecordingApiConfig } from './types'

const TOKEN_EXPIRY_LEEWAY_SECONDS = 10

export class ClickHouseCredential {
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
            logger.warn('[RecordingApi] ClickHouse token file is not readable, using the static password', {
                path,
                error: serializeError(error),
            })
            RecordingApiMetrics.incrementClickhousePasswordFallback('unreadable')
            return this.staticPassword
        }
        if (!token) {
            logger.warn('[RecordingApi] ClickHouse token file is empty, using the static password', { path })
            RecordingApiMetrics.incrementClickhousePasswordFallback('empty')
            return this.staticPassword
        }
        // The kubelet stops refreshing the token of a terminating pod, and ClickHouse rejects an expired token.
        if (this.staticPassword && tokenExpired(token, nowSeconds)) {
            logger.warn('[RecordingApi] ClickHouse token has expired, using the static password', { path })
            RecordingApiMetrics.incrementClickhousePasswordFallback('expired')
            return this.staticPassword
        }
        return token
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
