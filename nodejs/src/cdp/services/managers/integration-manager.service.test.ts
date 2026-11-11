import { register } from 'prom-client'

import { IntegrationType } from '~/cdp/types'
import { EncryptedFields } from '~/cdp/utils/encryption-utils'
import { IntegrationReference } from '~/cdp/utils/integration-reference'
import { DependencyUnavailableError } from '~/common/utils/db/error'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { logger } from '~/common/utils/logger'
import { PubSub } from '~/common/utils/pubsub'
import { createTestTeamFixture } from '~/tests/helpers/sql'
import { Hub } from '~/types'

import { createIntegration, insertIntegration } from '../../_tests/fixtures'
import { IntegrationManagerService } from './integration-manager.service'
import { IntegrationSource, IntegrationSourceRecord } from './integration-source'
import { PostgresIntegrationSource } from './postgres-integration-source'

const UUID_REFERENCE = '6f1c2a4e-8b3d-4c5e-9f7a-1b2c3d4e5f60'

class FakeIntegrationSource implements IntegrationSource {
    public readonly name = 'fake'
    public records: Record<IntegrationReference, Omit<IntegrationSourceRecord, 'reference'>> = {}
    public load = jest.fn((references: IntegrationReference[]) => {
        const result: Record<IntegrationReference, IntegrationSourceRecord> = {}
        for (const reference of references) {
            const record = this.records[reference]
            if (record) {
                result[reference] = { reference, ...record }
            }
        }
        return Promise.resolve(result)
    })
}

describe('IntegrationManagerService', () => {
    describe('with a fake source', () => {
        let source: FakeIntegrationSource
        let manager: IntegrationManagerService
        let now: number

        const advanceTo = (ms: number): void => {
            jest.spyOn(Date, 'now').mockReturnValue(now + ms)
        }

        beforeEach(() => {
            now = Date.now()
            advanceTo(0)
            source = new FakeIntegrationSource()
            source.records['5'] = { integration: createIntegration({ id: 5, team_id: 1 }), decryptFailures: [] }
            source.records[UUID_REFERENCE] = {
                integration: createIntegration({ id: 6, team_id: 1 }),
                decryptFailures: [],
            }
            manager = new IntegrationManagerService({ on: jest.fn() } as unknown as PubSub, source)
        })

        afterEach(() => {
            jest.restoreAllMocks()
        })

        it.each<[string, IntegrationReference | number]>([
            ['a legacy id as a number', 5],
            ['a legacy id as a string', '5'],
            ['a uuid reference', UUID_REFERENCE],
        ])('loads %s by its canonical reference', async (_, id) => {
            const integration = await manager.get(id)

            expect(integration).toBe(source.records[String(id)].integration)
            expect(source.load).toHaveBeenCalledWith([String(id)])
        })

        it('keys getMany by reference, so a number and its string share one entry', async () => {
            const integrations = await manager.getMany([5, '5', UUID_REFERENCE])

            expect(source.load).toHaveBeenCalledTimes(1)
            expect(source.load).toHaveBeenCalledWith(['5', UUID_REFERENCE])
            expect(Object.keys(integrations)).toEqual(['5', UUID_REFERENCE])
            expect(integrations[5]).toBe(source.records['5'].integration)
        })

        it('returns decrypt failures under the same key for a legacy number and string', async () => {
            const failures = [{ path: 'token', reason: 'undecryptable' as const }]
            source.records['5'].decryptFailures = failures

            const result = await manager.getDecryptFailures([5, '5'])

            expect(result).toEqual({ '5': failures })
            expect(result[5]).toBe(failures)
            expect(source.load).toHaveBeenCalledWith(['5'])
        })

        it.each([
            ['a clean record', UUID_REFERENCE],
            ['an unknown id', '7'],
        ])('returns no decrypt failures for %s', async (_, id) => {
            expect(await manager.getDecryptFailures([id])).toEqual({ [id]: [] })
        })

        it.each<[string, number | string]>([
            ['a negative number', -1],
            ['a fraction', 1.5],
            ['an unsafe integer', 2 ** 53],
            ['NaN', NaN],
            ['a leading zero', '05'],
            ['an empty string', ''],
            ['an uppercase uuid', UUID_REFERENCE.toUpperCase()],
            ['a number with spaces', ' 5'],
        ])('does not load %s', async (_, id) => {
            expect(await manager.get(id)).toBeNull()
            expect(await manager.getMany([id])).toEqual({})
            expect(source.load).not.toHaveBeenCalled()
        })

        it('returns null for a reference the source does not have', async () => {
            expect(await manager.get(7)).toBeNull()
            expect(await manager.getMany([7])).toEqual({ '7': null })
        })

        // The loader TTL is 60s plus up to 12s of jitter.
        it.each<[string, number | undefined, number, number]>([
            ['an expiry before the TTL', 10_000, 10_000, 10_001],
            ['an expiry in the past', -1, -1, 0],
            ['no expiry', undefined, 59_999, 72_001],
            ['an expiry after the TTL', 600_000, 59_999, 72_001],
        ])('with %s, serves from the cache until the earlier deadline', async (_, expiresInMs, cachedAt, reloadAt) => {
            source.records['5'].expiresAt = expiresInMs === undefined ? undefined : now + expiresInMs
            await manager.get(5)
            expect(source.load).toHaveBeenCalledTimes(1)

            if (cachedAt >= 0) {
                advanceTo(cachedAt)
                await manager.get(5)
                expect(source.load).toHaveBeenCalledTimes(1)
            }

            advanceTo(reloadAt)
            await manager.get(5)
            expect(source.load).toHaveBeenCalledTimes(2)
        })

        it('reloads an id from a reload message, given as a number', async () => {
            await manager.get(5)
            manager['onIntegrationsReloaded']([5])
            await manager.get('5')

            expect(source.load).toHaveBeenCalledTimes(2)
        })

        it('reports decrypt failures with a metric and a log that has no values', async () => {
            const secret = 'gAAAAAsecret-ciphertext'
            source.records['5'] = {
                integration: createIntegration({
                    id: 5,
                    team_id: 1,
                    kind: 'slack',
                    sensitive_config: { token: secret },
                }),
                decryptFailures: [{ path: 'token', reason: 'undecryptable' }],
            }
            const failures = async (): Promise<number> => {
                const metric = await register.getSingleMetric('cdp_integration_decrypt_failures_total')?.get()
                return (metric?.values ?? [])
                    .filter(({ labels }) => labels.source === 'fake' && labels.reason === 'undecryptable')
                    .reduce((sum, { value }) => sum + value, 0)
            }
            const before = await failures()
            const warn = jest.spyOn(logger, 'warn').mockImplementation(() => {})

            const integration = await manager.get(5)

            expect(integration?.sensitive_config).toEqual({ token: secret })
            expect(await failures()).toBe(before + 1)
            expect(warn).toHaveBeenCalledTimes(1)
            expect(warn.mock.calls[0][2]).toEqual({
                reference: '5',
                teamId: 1,
                kind: 'slack',
                source: 'fake',
                failures: [{ path: 'token', reason: 'undecryptable' }],
            })
            expect(JSON.stringify(warn.mock.calls)).not.toContain(secret)
        })
    })

    describe('with the postgres source', () => {
        jest.setTimeout(2000)
        let hub: Hub
        let source: PostgresIntegrationSource
        let manager: IntegrationManagerService
        let integrations: IntegrationType[]
        let teamId1: number

        beforeEach(async () => {
            hub = await createHub()
            source = new PostgresIntegrationSource(hub.postgres, hub.encryptedFields)
            manager = new IntegrationManagerService(hub.pubSub, source)

            teamId1 = (await createTestTeamFixture(hub.postgres)).team.id

            integrations = []

            integrations.push(
                await insertIntegration(hub.postgres, teamId1, {
                    id: teamId1,
                    kind: 'slack',
                    config: { team: 'foobar' },
                    sensitive_config: {
                        access_token: hub.encryptedFields.encrypt('token'),
                        not_encrypted: 'not-encrypted',
                    },
                })
            )
        })

        afterEach(async () => {
            jest.restoreAllMocks()
            await closeHub(hub)
        })

        it.each([
            ['a number', (id: number): number | string => id],
            ['a string', (id: number): number | string => String(id)],
        ])('returns the integrations for an id given as %s', async (_, toId) => {
            const items = await manager.getMany([toId(integrations[0].id)])

            expect(items).toEqual({
                [teamId1]: {
                    config: {
                        team: 'foobar',
                    },
                    id: teamId1,
                    kind: 'slack',
                    sensitive_config: {
                        access_token: 'token',
                        not_encrypted: 'not-encrypted',
                    },
                    team_id: teamId1,
                },
            })
        })

        it('does not query for a uuid reference, because the table has none', async () => {
            const query = jest.spyOn(hub.postgres, 'query')

            expect(await source.load([UUID_REFERENCE])).toEqual({})
            expect(query).not.toHaveBeenCalled()
        })

        it('does not fail the batch for an id past the int4 range', async () => {
            const records = await source.load([String(integrations[0].id), '3000000000'])

            expect(Object.keys(records)).toEqual([String(integrations[0].id)])
        })

        it('marks the fields that do not decrypt, and keeps the same values as before for them', async () => {
            const otherKeyFields = new EncryptedFields('f'.repeat(32))
            const undecryptable = otherKeyFields.encrypt('legacy-token')
            const sensitiveConfig = {
                access_token: undecryptable,
                refresh_token: hub.encryptedFields.encrypt(hub.encryptedFields.encrypt('refresh')),
                nested: { keys: [hub.encryptedFields.encrypt('ok'), undecryptable] },
                not_encrypted: 'not-encrypted',
            }
            const row = await insertIntegration(hub.postgres, teamId1, { sensitive_config: sensitiveConfig })

            const record = (await source.load([String(row.id)]))[String(row.id)]

            expect(record.integration.sensitive_config).toEqual(
                hub.encryptedFields.decryptObject(sensitiveConfig, { ignoreDecryptionErrors: true })
            )
            // jsonb does not keep key order.
            expect(record.decryptFailures).toHaveLength(3)
            expect(record.decryptFailures).toEqual(
                expect.arrayContaining([
                    { path: 'access_token', reason: 'undecryptable' },
                    { path: 'refresh_token', reason: 'nested_ciphertext' },
                    { path: 'nested.keys.1', reason: 'undecryptable' },
                ])
            )
        })

        it('retries the lookup when the read replica cancels it', async () => {
            const cancelled = new Error('Canceling statement due to conflict with recovery.')
            jest.spyOn(hub.postgres, 'query').mockRejectedValueOnce(
                new DependencyUnavailableError(cancelled.message, 'Postgres', cancelled)
            )

            const item = await manager.get(integrations[0].id)

            expect(item?.config).toEqual({ team: 'foobar' })
        })

        it('updates cached integration data when integration changes', async () => {
            // First check - initial state
            const item = await manager.get(integrations[0].id)
            expect(item?.config).toEqual({ team: 'foobar' })
            expect(item?.sensitive_config).toEqual({ access_token: 'token', not_encrypted: 'not-encrypted' })

            // Update the integration in the database
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `UPDATE posthog_integration
                     SET config = jsonb_set(config, '{team}', '"updated-team"'::jsonb),
                         sensitive_config = jsonb_set(sensitive_config, '{access_token}', $1::jsonb)
                     WHERE id = $2`,
                [JSON.stringify(hub.encryptedFields.encrypt('updated-token')), integrations[0].id],
                'updateIntegration'
            )

            manager['onIntegrationsReloaded']([integrations[0].id])

            // Verify the database update worked
            const updatedIntegration = await hub.postgres.query(
                PostgresUse.COMMON_READ,
                `SELECT config, sensitive_config FROM posthog_integration WHERE id = $1`,
                [integrations[0].id],
                'fetchUpdatedIntegration'
            )

            // assert the integration was updated
            expect(updatedIntegration.rows[0].config).toEqual({ team: 'updated-team' })
            expect(hub.encryptedFields.decrypt(updatedIntegration.rows[0].sensitive_config.access_token)).toEqual(
                'updated-token'
            )

            // Trigger integration reload
            manager['onIntegrationsReloaded']([integrations[0].id])
            // Check if the cached data was updated
            const reloadedIntegrations = await manager.get(integrations[0].id)
            expect(reloadedIntegrations?.config).toEqual({ team: 'updated-team' })
            expect(reloadedIntegrations?.sensitive_config).toEqual({
                access_token: 'updated-token',
                not_encrypted: 'not-encrypted',
            })
        })
    })
})
