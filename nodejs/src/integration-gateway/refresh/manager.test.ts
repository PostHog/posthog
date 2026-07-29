import { EncryptedFields } from '~/cdp/utils/encryption-utils'
import { fetch } from '~/common/utils/request'
import { RedisPool } from '~/types'

import { IntegrationRepository } from '../repository'
import { IntegrationRow } from '../types'
import { nowSecs } from './expiry'
import { RefreshManager, RefreshManagerConfig } from './manager'

jest.mock('~/common/utils/request', () => ({
    ...jest.requireActual('~/common/utils/request'),
    fetch: jest.fn(),
}))
const mockFetch = fetch as jest.Mock

const SALT = '00beef0000beef0000beef0000beef00'

function makeConfig(overrides: Partial<RefreshManagerConfig> = {}): RefreshManagerConfig {
    return {
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
        INTEGRATION_GATEWAY_REFRESH_TOKEN_URL_OVERRIDE: 'https://oauth.test/token',
        INTEGRATION_GATEWAY_REFRESH_KINDS: 'hubspot',
        INTEGRATION_GATEWAY_REFRESH_LOCK_TTL_SECONDS: 30,
        INTEGRATION_GATEWAY_REFRESH_HTTP_TIMEOUT_MS: 10000,
        ...overrides,
    }
}

function mockTokenResponse(status: number, body: Record<string, any>): void {
    mockFetch.mockResolvedValue({
        status,
        json: () => Promise.resolve(body),
        text: () => Promise.resolve(JSON.stringify(body)),
        dump: () => Promise.resolve(),
    })
}

function setup(
    opts: {
        rowOverrides?: Partial<IntegrationRow>
        lockResult?: 'OK' | null
        config?: Partial<RefreshManagerConfig>
    } = {}
) {
    const encryptedFields = new EncryptedFields(SALT)
    const row: IntegrationRow = {
        id: 1,
        team_id: 2,
        kind: 'hubspot',
        config: { refreshed_at: nowSecs() - 3000, expires_in: 3600 },
        sensitive_config: {
            access_token: encryptedFields.encrypt('old-access'),
            refresh_token: encryptedFields.encrypt('old-refresh'),
        },
        ...opts.rowOverrides,
    }
    const repository = {
        fetchOne: jest.fn().mockResolvedValue(row),
        updateAfterRefresh: jest.fn().mockResolvedValue(undefined),
        markRefreshFailed: jest.fn().mockResolvedValue(undefined),
    } as unknown as jest.Mocked<IntegrationRepository>
    const lockResult = opts.lockResult === undefined ? 'OK' : opts.lockResult
    const client = { set: jest.fn().mockResolvedValue(lockResult), del: jest.fn().mockResolvedValue(1) }
    const redisPool = {
        acquire: jest.fn().mockResolvedValue(client),
        release: jest.fn().mockResolvedValue(undefined),
    } as unknown as RedisPool
    const manager = new RefreshManager(repository, encryptedFields, redisPool, makeConfig(opts.config), ['hubspot'])
    return { manager, repository, encryptedFields, row, client }
}

describe('RefreshManager', () => {
    it('refreshes an expired token, re-encrypting the new tokens and writing them back', async () => {
        mockTokenResponse(200, { access_token: 'new-access', expires_in: 1800, refresh_token: 'new-refresh' })
        const { manager, repository, encryptedFields, row } = setup()

        const result = await manager.refresh(row)

        expect(repository.updateAfterRefresh).toHaveBeenCalledTimes(1)
        const [id, newConfig, newSensitive] = repository.updateAfterRefresh.mock.calls[0]
        expect(id).toBe(1)
        expect(newConfig.expires_in).toBe(1800)
        expect(newConfig.refreshed_at).toBeGreaterThan(nowSecs() - 5)
        // Written back encrypted (never plaintext), and Django-readable via the primary key.
        expect(encryptedFields.decrypt(newSensitive.access_token)).toBe('new-access')
        expect(encryptedFields.decrypt(newSensitive.refresh_token)).toBe('new-refresh')
        // The returned row carries the refreshed credentials for the read path.
        expect(encryptedFields.decrypt(result.sensitive_config.access_token)).toBe('new-access')

        const [url, options] = mockFetch.mock.calls[0]
        expect(url).toBe('https://oauth.test/token')
        expect(options.body).toContain('grant_type=refresh_token')
        expect(options.body).toContain('refresh_token=old-refresh')
        expect(options.body).toContain('client_id=cid')
    })

    it('does nothing when the token is still fresh (no HTTP call, no write)', async () => {
        const { manager, repository, row } = setup({
            rowOverrides: { config: { refreshed_at: nowSecs(), expires_in: 3600 } },
        })
        const result = await manager.refresh(row)
        expect(result).toBe(row)
        expect(mockFetch).not.toHaveBeenCalled()
        expect(repository.updateAfterRefresh).not.toHaveBeenCalled()
    })

    it('skips (serves the current token) when another head holds the lock', async () => {
        const { manager, repository, row } = setup({ lockResult: null })
        const result = await manager.refresh(row)
        expect(result).toBe(row)
        expect(mockFetch).not.toHaveBeenCalled()
        expect(repository.updateAfterRefresh).not.toHaveBeenCalled()
    })

    it('marks the integration failed and serves the old token when the provider errors', async () => {
        mockTokenResponse(400, { error: 'invalid_grant' })
        const { manager, repository, encryptedFields, row } = setup()
        const result = await manager.refresh(row)
        expect(repository.markRefreshFailed).toHaveBeenCalledWith(1)
        expect(repository.updateAfterRefresh).not.toHaveBeenCalled()
        expect(encryptedFields.decrypt(result.sensitive_config.access_token)).toBe('old-access')
    })

    it('marks failed when the integration has no stored refresh_token', async () => {
        const seed = new EncryptedFields(SALT)
        const row: IntegrationRow = {
            id: 1,
            team_id: 2,
            kind: 'hubspot',
            config: { refreshed_at: nowSecs() - 3000, expires_in: 3600 },
            sensitive_config: { access_token: seed.encrypt('old-access') },
        }
        const { manager, repository } = setup({ rowOverrides: { sensitive_config: row.sensitive_config } })
        // fetchOne re-reads the (also refresh-token-less) row under the lock.
        ;(repository.fetchOne as jest.Mock).mockResolvedValue(row)
        await manager.refresh(row)
        expect(repository.markRefreshFailed).toHaveBeenCalledWith(1)
        expect(mockFetch).not.toHaveBeenCalled()
    })

    it('skips without touching Redis when the kind has no configured provider', async () => {
        const { manager, repository, client, row } = setup({
            config: { HUBSPOT_APP_CLIENT_ID: '', HUBSPOT_APP_CLIENT_SECRET: '' },
        })
        const result = await manager.refresh(row)
        expect(result).toBe(row)
        expect(client.set).not.toHaveBeenCalled()
        expect(repository.updateAfterRefresh).not.toHaveBeenCalled()
    })
})
