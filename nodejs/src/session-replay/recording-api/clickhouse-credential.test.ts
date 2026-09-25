import jwt from 'jsonwebtoken'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { register } from 'prom-client'

import { overrideConfigWithEnv } from '~/common/config/config'
import { getDefaultSessionRecordingApiConfig } from '~/ingestion/pipelines/sessionreplay/config'

import { ClickHouseCredential } from './clickhouse-credential'

const NOW = 1_000_000
const FALLBACK_METRIC = 'recording_api_clickhouse_password_fallback_total'

const tokenExpiringAt = (exp: number): string => jwt.sign({ exp }, 'test-secret')
const liveToken = tokenExpiringAt(NOW + 3600)
const expiredToken = tokenExpiringAt(NOW - 60)
const withinLeewayToken = tokenExpiringAt(NOW + 5)
const noExpToken = jwt.sign({ sub: 'system:serviceaccount:recording-api:recording-api' }, 'test-secret', {
    noTimestamp: true,
})
const malformedPayloadToken = `${Buffer.from('{"alg":"RS256","typ":"JWT"}').toString('base64url')}.bm90LWpzb24.signature`

describe('ClickHouseCredential', () => {
    let dir: string

    beforeEach(() => {
        dir = mkdtempSync(join(tmpdir(), 'clickhouse-credential-'))
        register.getSingleMetric(FALLBACK_METRIC)?.reset()
    })

    afterEach(() => {
        rmSync(dir, { recursive: true, force: true })
    })

    it.each([
        ['live token', `${liveToken}\n`, 'static', liveToken, undefined],
        ['no token file configured', null, 'static', 'static', undefined],
        ['missing file', undefined, 'static', 'static', 'unreadable'],
        ['empty file', ' \n', 'static', 'static', 'empty'],
        ['expired token', expiredToken, 'static', 'static', 'expired'],
        ['expired token, no static', expiredToken, '', expiredToken, undefined],
        ['inside the leeway', withinLeewayToken, 'static', 'static', 'expired'],
        ['no exp claim', noExpToken, 'static', noExpToken, undefined],
        ['malformed payload', malformedPayloadToken, 'static', malformedPayloadToken, undefined],
        ['opaque token', 'not-a-jwt', 'static', 'not-a-jwt', undefined],
    ])('%s', async (_case, contents, staticPassword, expected, fallbackReason) => {
        const tokenFile = contents === null ? '' : join(dir, 'token')
        if (typeof contents === 'string') {
            writeFileSync(tokenFile, contents)
        }
        const credential = new ClickHouseCredential('recording_api', staticPassword, tokenFile)

        await expect(credential.password(NOW)).resolves.toEqual(expected)
        const fallbacks = (await register.getSingleMetric(FALLBACK_METRIC)?.get())?.values ?? []
        expect(fallbacks.map(({ labels }) => labels.reason)).toEqual(fallbackReason ? [fallbackReason] : [])
    })

    it('reads the token file named by CLICKHOUSE_PASSWORD_FILE', async () => {
        const tokenFile = join(dir, 'token')
        writeFileSync(tokenFile, 'the-token')
        const config = overrideConfigWithEnv(getDefaultSessionRecordingApiConfig(), {
            CLICKHOUSE_USER: 'recording_api',
            CLICKHOUSE_PASSWORD: 'static',
            CLICKHOUSE_PASSWORD_FILE: tokenFile,
        })

        await expect(ClickHouseCredential.fromConfig(config).auth()).resolves.toEqual({
            username: 'recording_api',
            password: 'the-token',
        })
    })
})
