import { Hub } from '../src/types'
import { createHub } from '../src/utils/db/hub'
import { PluginsApiKeyManager } from '../src/worker/vm/extensions/helpers/api-key-manager'
import { createUserTeamAndOrganization } from './helpers/sql'
import { POSTGRES_TRUNCATE_TABLES_QUERY } from './helpers/sql'

describe('PluginsApiKeyManager', () => {
    let hub: Hub
    let closeHub: () => Promise<void>

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub({
            TASK_TIMEOUT: 1,
        })
        await hub.db.postgresQuery(POSTGRES_TRUNCATE_TABLES_QUERY, [], 'truncateTablesTest')
    })

    afterEach(async () => {
        await closeHub()
    })

    test('PluginsApiKeyManager', async () => {
        const pluginsApiKeyManager = new PluginsApiKeyManager(hub.db)

        const orgId1 = '0174f81e-36f5-0000-7ef8-cc26c1fbab1c'
        const orgId2 = '4dc8564d-bd82-1065-2f40-97f7c50f67cf'

        jest.spyOn(hub.db, 'createUser')

        await createUserTeamAndOrganization(hub!.postgres, 88, 8888, 'a73fc995-a63f-4e4e-bf65-2a5e9f93b2b2', orgId1)

        await createUserTeamAndOrganization(
            hub!.postgres,
            99,
            9999,
            '017d107d-219a-0000-ddef-84f776dcf22b',
            orgId2,
            '017d107d-21a2-0001-4032-b47cdf5e09dc'
        )

        const key1 = await pluginsApiKeyManager.fetchOrCreatePersonalApiKey(orgId1)
        expect(hub.db.createUser).toHaveBeenCalledTimes(1)
        expect(hub.db.createUser).toHaveBeenCalledWith(
            expect.objectContaining({
                organizationMembershipLevel: 8,
                organization_id: orgId1,
            })
        )

        const key2 = await pluginsApiKeyManager.fetchOrCreatePersonalApiKey(orgId2)
        expect(hub.db.createUser).toHaveBeenCalledTimes(2)
        expect(hub.db.createUser).toHaveBeenCalledWith(
            expect.objectContaining({
                organizationMembershipLevel: 8,
                organization_id: orgId2,
            })
        )

        // check that we've created two bots with two distinct keys
        expect(key1).not.toEqual(key2)

        // check that we hit the cache
        await pluginsApiKeyManager.fetchOrCreatePersonalApiKey(orgId1)

        expect(hub.db.createUser).toHaveBeenCalledTimes(2)
        expect(pluginsApiKeyManager.pluginsApiKeyCache.get(orgId1)?.[0]).toEqual(key1)
        expect(pluginsApiKeyManager.pluginsApiKeyCache.get(orgId2)?.[0]).toEqual(key2)
    })
})
