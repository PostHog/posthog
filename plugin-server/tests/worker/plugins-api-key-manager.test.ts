import { Hub } from '../../src/types'
import { closeHub, createHub } from '../../src/utils/db/hub'
import { PluginsApiKeyManager } from '../../src/worker/vm/extensions/helpers/api-key-manager'
import { clearDatabase, createUserTeamAndOrganization } from '../helpers/sql'

const ORG_ID_1 = '0174f81e-36f5-0000-7ef8-cc26c1fbab1c'
const ORG_ID_2 = '4dc8564d-bd82-1065-2f40-97f7c50f67cf'

describe('PluginsApiKeyManager', () => {
    let hub: Hub

    beforeEach(async () => {
        hub = await createHub({
            TASK_TIMEOUT: 1,
        })
        await clearDatabase(hub.db.postgres)
        await hub.db.redisExpire(`plugins-api-key-manager/${ORG_ID_1}`, 0)
        await hub.db.redisExpire(`plugins-api-key-manager/${ORG_ID_2}`, 0)
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    test('fetchOrCreatePersonalApiKey', async () => {
        const pluginsApiKeyManager = new PluginsApiKeyManager(hub.db)

        jest.spyOn(hub.db, 'createUser')

        await createUserTeamAndOrganization(hub!.postgres, 88, 8888, 'a73fc995-a63f-4e4e-bf65-2a5e9f93b2b2', ORG_ID_1)

        await createUserTeamAndOrganization(
            hub!.postgres,
            99,
            9999,
            '017d107d-219a-0000-ddef-84f776dcf22b',
            ORG_ID_2,
            '017d107d-21a2-0001-4032-b47cdf5e09dc'
        )

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
