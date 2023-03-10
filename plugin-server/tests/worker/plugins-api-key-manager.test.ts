import { Hub } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
import { PluginsApiKeyManager } from '../../src/worker/vm/extensions/helpers/api-key-manager'
import { createUserTeamAndOrganization } from '../helpers/sql'

describe('PluginsApiKeyManager', () => {
    let hub: Hub
    let closeHub: () => Promise<void>

    beforeAll(async () => {
        ;[hub, closeHub] = await createHub({
            TASK_TIMEOUT: 1,
        })
    })

    afterAll(async () => {
        await closeHub()
    })

    test('fetchOrCreatePersonalApiKey', async () => {
        const pluginsApiKeyManager = new PluginsApiKeyManager(hub.db)

        jest.spyOn(hub.db, 'createUser')

        const { organizationId: ORG_ID_1 } = await createUserTeamAndOrganization({})

        const { organizationId: ORG_ID_2 } = await createUserTeamAndOrganization({})

        await hub.db.redisExpire(`plugins-api-key-manager/${ORG_ID_1}`, 0)
        await hub.db.redisExpire(`plugins-api-key-manager/${ORG_ID_2}`, 0)

        const key1 = await pluginsApiKeyManager.fetchOrCreatePersonalApiKey(ORG_ID_1)
        expect(hub.db.createUser).toHaveBeenCalledTimes(1)
        expect(hub.db.createUser).toHaveBeenCalledWith(
            expect.objectContaining({
                organizationMembershipLevel: 8,
                organization_id: ORG_ID_1,
            })
        )

        const key2 = await pluginsApiKeyManager.fetchOrCreatePersonalApiKey(ORG_ID_2)
        expect(hub.db.createUser).toHaveBeenCalledTimes(2)
        expect(hub.db.createUser).toHaveBeenCalledWith(
            expect.objectContaining({
                organizationMembershipLevel: 8,
                organization_id: ORG_ID_2,
            })
        )

        // check that we've created two bots with two distinct keys
        expect(key1).not.toEqual(key2)

        // check that we hit the cache
        const key = await pluginsApiKeyManager.fetchOrCreatePersonalApiKey(ORG_ID_1)

        expect(hub.db.createUser).toHaveBeenCalledTimes(2)

        // What happens when the key still exists, but it's not in the cache anymore
        await hub.db.redisExpire(`plugins-api-key-manager/${ORG_ID_1}`, 0)

        const newKey = await pluginsApiKeyManager.fetchOrCreatePersonalApiKey(ORG_ID_1)
        expect(newKey).not.toEqual(key)
    })
})
