import http from 'http'
import { AddressInfo } from 'net'

import { insertIntegration } from '~/cdp/_tests/fixtures'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { EncryptedFields } from '~/common/utils/encryption-utils'
import { createTeam, getTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub } from '~/types'

import { IntegrationRepository } from '../repository'
import { nowSecs } from './expiry'
import { RefreshManager, RefreshManagerConfig } from './manager'

const SALT = '00beef0000beef0000beef0000beef00'

describe('RefreshManager (real DB + Redis + mock OAuth)', () => {
    let hub: Hub
    let encryptedFields: EncryptedFields
    let repository: IntegrationRepository
    let teamId: number
    let server: http.Server
    let tokenUrl: string
    let lastRequestBody: string

    beforeAll(async () => {
        server = http.createServer((req, res) => {
            let body = ''
            req.on('data', (chunk) => (body += chunk))
            req.on('end', () => {
                lastRequestBody = body
                res.writeHead(200, { 'content-type': 'application/json' })
                res.end(
                    JSON.stringify({
                        access_token: 'refreshed-access',
                        expires_in: 1800,
                        refresh_token: 'rotated-refresh',
                    })
                )
            })
        })
        await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', () => resolve()))
        tokenUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}/token`
    })

    afterAll(async () => {
        await new Promise<void>((resolve) => server.close(() => resolve()))
    })

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()
        encryptedFields = new EncryptedFields(SALT)
        repository = new IntegrationRepository(hub.postgres)
        const team = await getTeam(hub.postgres, 2)
        teamId = await createTeam(hub.postgres, team!.organization_id)
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    const config = (): RefreshManagerConfig => ({
        HUBSPOT_APP_CLIENT_ID: 'cid',
        HUBSPOT_APP_CLIENT_SECRET: 'sec',
        SALESFORCE_CONSUMER_KEY: '',
        SALESFORCE_CONSUMER_SECRET: '',
        GOOGLE_ADS_APP_CLIENT_ID: '',
        GOOGLE_ADS_APP_CLIENT_SECRET: '',
        GOOGLE_ANALYTICS_APP_CLIENT_ID: '',
        GOOGLE_ANALYTICS_APP_CLIENT_SECRET: '',
        GOOGLE_SEARCH_CONSOLE_APP_CLIENT_ID: '',
        GOOGLE_SEARCH_CONSOLE_APP_CLIENT_SECRET: '',
        SOCIAL_AUTH_GOOGLE_OAUTH2_KEY: '',
        SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET: '',
        INTEGRATION_GATEWAY_REFRESH_TOKEN_URL_OVERRIDE: tokenUrl,
        INTEGRATION_GATEWAY_REFRESH_KINDS: 'hubspot',
        INTEGRATION_GATEWAY_REFRESH_LOCK_TTL_SECONDS: 30,
        INTEGRATION_GATEWAY_REFRESH_HTTP_TIMEOUT_MS: 10000,
    })

    const seedExpiredHubspot = async () =>
        insertIntegration(hub.postgres, teamId, {
            kind: 'hubspot',
            config: { refreshed_at: nowSecs() - 3000, expires_in: 3600 },
            sensitive_config: {
                access_token: encryptedFields.encrypt('stale-access'),
                refresh_token: encryptedFields.encrypt('stored-refresh'),
            },
        })

    it('refreshes an expired token end-to-end: calls the provider, re-encrypts, and persists', async () => {
        const integration = await seedExpiredHubspot()
        const manager = new RefreshManager(repository, encryptedFields, hub.redisPool, config(), ['hubspot'], '*')

        const row = (await repository.fetchOne(integration.id))!
        const updated = await manager.refresh(row)

        // Returned row carries the new token for the read path.
        expect(encryptedFields.decrypt(updated.sensitive_config.access_token)).toBe('refreshed-access')
        // The provider was actually called with the stored refresh token.
        expect(lastRequestBody).toContain('grant_type=refresh_token')
        expect(lastRequestBody).toContain('refresh_token=stored-refresh')

        // Persisted to the DB, re-encrypted, timing updated, errors cleared.
        const persisted = (await repository.fetchOne(integration.id))!
        expect(encryptedFields.decrypt(persisted.sensitive_config.access_token)).toBe('refreshed-access')
        expect(encryptedFields.decrypt(persisted.sensitive_config.refresh_token)).toBe('rotated-refresh')
        expect(persisted.config.expires_in).toBe(1800)
        expect(persisted.config.refreshed_at).toBeGreaterThan(nowSecs() - 60)

        const errors = await hub.postgres.query(
            PostgresUse.COMMON_READ,
            `SELECT errors FROM posthog_integration WHERE id = $1`,
            [integration.id],
            'test-check-errors'
        )
        expect(errors.rows[0].errors).toBe('')
    })

    it('honors the real Redis single-flight lock: a held lock skips the refresh', async () => {
        const integration = await seedExpiredHubspot()
        const manager = new RefreshManager(repository, encryptedFields, hub.redisPool, config(), ['hubspot'], '*')
        const row = (await repository.fetchOne(integration.id))!

        // Pre-hold the lock so the manager observes it as taken.
        const client = await hub.redisPool.acquire()
        try {
            await client.set(`integration-gateway:refresh-lock:${integration.id}`, '1', 'EX', 30, 'NX')
        } finally {
            await hub.redisPool.release(client)
        }

        const result = await manager.refresh(row)

        // No refresh happened; the original (stale-but-valid) token is served and the DB is untouched.
        expect(encryptedFields.decrypt(result.sensitive_config.access_token)).toBe('stale-access')
        const persisted = (await repository.fetchOne(integration.id))!
        expect(encryptedFields.decrypt(persisted.sensitive_config.access_token)).toBe('stale-access')
    })
})
