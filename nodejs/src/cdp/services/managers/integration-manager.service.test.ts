import { IntegrationType } from '~/cdp/types'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { createTeam, getTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub } from '~/types'

import { insertIntegration } from '../../_tests/fixtures'
import { IntegrationGatewayService } from './integration-gateway.service'
import { IntegrationManagerService } from './integration-manager.service'

describe('IntegrationManager', () => {
    jest.setTimeout(2000)
    let hub: Hub
    let manager: IntegrationManagerService
    let integrations: IntegrationType[]
    let teamId1: number

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()
        manager = new IntegrationManagerService(hub.pubSub, hub.postgres, hub.encryptedFields)

        const team = await getTeam(hub.postgres, 2)

        teamId1 = await createTeam(hub.postgres, team!.organization_id)

        integrations = []

        integrations.push(
            await insertIntegration(hub.postgres, teamId1, {
                id: 1,
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
        await closeHub(hub)
    })

    it('returns the integrations', async () => {
        const items = await manager.getMany([integrations[0].id], teamId1)

        expect(items).toEqual({
            '1': {
                config: {
                    team: 'foobar',
                },
                id: 1,
                kind: 'slack',
                sensitive_config: {
                    access_token: 'token',
                    not_encrypted: 'not-encrypted',
                },
                team_id: teamId1,
            },
        })
    })

    it('updates cached integration data when integration changes', async () => {
        // First check - initial state
        const item = await manager.get(integrations[0].id, teamId1)
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
        const reloadedIntegrations = await manager.get(integrations[0].id, teamId1)
        expect(reloadedIntegrations?.config).toEqual({ team: 'updated-team' })
        expect(reloadedIntegrations?.sensitive_config).toEqual({
            access_token: 'updated-token',
            not_encrypted: 'not-encrypted',
        })
    })

    describe('gateway routing', () => {
        const withGateway = (gateway: Partial<IntegrationGatewayService>): IntegrationManagerService =>
            new IntegrationManagerService(
                hub.pubSub,
                hub.postgres,
                hub.encryptedFields,
                gateway as unknown as IntegrationGatewayService
            )

        it('reads through the gateway when it is enabled for the team', async () => {
            const gatewayResult = {
                '1': { id: 1, team_id: teamId1, kind: 'slack', config: {}, sensitive_config: { access_token: 'gw' } },
            }
            const fetchMany = jest.fn().mockResolvedValue(gatewayResult)
            const manager = withGateway({ enabledForTeam: () => true, fetchMany })

            const items = await manager.getMany([1], teamId1)

            expect(items).toEqual(gatewayResult)
            expect(fetchMany).toHaveBeenCalledWith([1], teamId1)
        })

        it('falls back to Postgres when the gateway errors', async () => {
            const manager = withGateway({
                enabledForTeam: () => true,
                fetchMany: jest.fn().mockRejectedValue(new Error('gateway down')),
            })

            const items = await manager.getMany([integrations[0].id], teamId1)

            expect(items['1']?.sensitive_config.access_token).toBe('token')
        })

        it('does not call the gateway when it is disabled for the team', async () => {
            const fetchMany = jest.fn()
            const manager = withGateway({ enabledForTeam: () => false, fetchMany })

            const items = await manager.getMany([integrations[0].id], teamId1)

            expect(fetchMany).not.toHaveBeenCalled()
            expect(items['1']?.sensitive_config.access_token).toBe('token')
        })
    })
})
