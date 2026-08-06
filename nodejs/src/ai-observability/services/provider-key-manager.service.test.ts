import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { createTeam, getTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub } from '~/types'

import { insertProviderKey } from '../_tests/fixtures'
import { ProviderKey, ProviderKeyManagerService } from './provider-key-manager.service'

describe('ProviderKeyManagerService', () => {
    jest.setTimeout(2000)
    let hub: Hub
    let manager: ProviderKeyManagerService
    let teamId: number
    let providerKey: ProviderKey

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()
        manager = new ProviderKeyManagerService(hub.postgres, hub.pubSub)

        const team = await getTeam(hub.postgres, 2)
        teamId = await createTeam(hub.postgres, team!.organization_id)
        providerKey = await insertProviderKey(hub.postgres, teamId)
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    it('returns provider key state', async () => {
        const item = await manager.getProviderKey(providerKey.id)

        expect(item).toMatchObject({
            id: providerKey.id,
            team_id: teamId,
            state: 'ok',
        })
    })

    it('returns null for unknown provider keys', async () => {
        const item = await manager.getProviderKey('00000000-0000-0000-0000-000000000000')

        expect(item).toBeNull()
    })

    it('uses cache until a provider key reload is requested', async () => {
        await expect(manager.getProviderKey(providerKey.id)).resolves.toMatchObject({ state: 'ok' })

        await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE llm_analytics_llmproviderkey SET state = 'error' WHERE id = $1`,
            [providerKey.id],
            'testUpdateProviderKeyState'
        )

        await expect(manager.getProviderKey(providerKey.id)).resolves.toMatchObject({ state: 'ok' })

        manager['onProviderKeysReloaded']([providerKey.id])

        await expect(manager.getProviderKey(providerKey.id)).resolves.toMatchObject({ state: 'error' })
    })
})
