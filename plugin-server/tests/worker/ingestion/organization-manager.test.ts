import { mocked } from 'ts-jest/utils'

import { Hub } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { UUIDT } from '../../../src/utils/utils'
import { OrganizationManager } from '../../../src/worker/ingestion/organization-manager'
import { commonOrganizationId } from '../../helpers/plugins'
import { resetTestDatabase } from '../../helpers/sql'

describe('OrganizationManager()', () => {
    let hub: Hub
    let closeHub: () => Promise<void>
    let organizationManager: OrganizationManager

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub()
        await resetTestDatabase()
        organizationManager = new OrganizationManager(hub.db)
    })
    afterEach(async () => {
        await closeHub()
    })

    describe('fetchOrganization()', () => {
        it('fetches and caches the team', async () => {
            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:05').getTime())
            jest.spyOn(hub.db, 'postgresQuery')

            let organization = await organizationManager.fetchOrganization(commonOrganizationId)

            expect(organization!.name).toEqual('TEST ORG')

            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:25').getTime())
            await hub.db.postgresQuery("UPDATE posthog_organization SET name = 'Updated Name!'", undefined, 'testTag')

            mocked(hub.db.postgresQuery).mockClear()

            organization = await organizationManager.fetchOrganization(commonOrganizationId)

            expect(organization!.name).toEqual('TEST ORG')
            expect(hub.db.postgresQuery).toHaveBeenCalledTimes(0)

            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:36').getTime())

            organization = await organizationManager.fetchOrganization(commonOrganizationId)

            expect(organization!.name).toEqual('Updated Name!')
            expect(hub.db.postgresQuery).toHaveBeenCalledTimes(1)
        })

        it('returns null when no such team', async () => {
            expect(await organizationManager.fetchOrganization(new UUIDT().toString())).toEqual(null)
        })
    })
})
