import { Hub } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { PostgresUse } from '../../../src/utils/db/postgres'
import { UUIDT } from '../../../src/utils/utils'
import { OrganizationManager } from '../../../src/worker/ingestion/organization-manager'
import { commonOrganizationId } from '../../helpers/plugins'
import { resetTestDatabase } from '../../helpers/sql'

jest.mock('../../../src/utils/status')

describe('OrganizationManager()', () => {
    let hub: Hub
    let closeHub: () => Promise<void>
    let organizationManager: OrganizationManager

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub()
        await resetTestDatabase()
        organizationManager = new OrganizationManager(hub.postgres, hub.teamManager)
    })
    afterEach(async () => {
        await closeHub()
    })

    describe('fetchOrganization()', () => {
        it('fetches and caches the team', async () => {
            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:05').getTime())
            jest.spyOn(hub.postgres, 'query')

            let organization = await organizationManager.fetchOrganization(commonOrganizationId)

            expect(organization!.name).toEqual('TEST ORG')

            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:25').getTime())
            await hub.db.postgres.query(
                PostgresUse.COMMON_WRITE,
                "UPDATE posthog_organization SET name = 'Updated Name!'",
                undefined,
                'testTag'
            )

            jest.mocked(hub.postgres.query).mockClear()

            organization = await organizationManager.fetchOrganization(commonOrganizationId)

            expect(organization!.name).toEqual('TEST ORG')
            expect(hub.postgres.query).toHaveBeenCalledTimes(0)

            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:36').getTime())

            organization = await organizationManager.fetchOrganization(commonOrganizationId)

            expect(organization!.name).toEqual('Updated Name!')
            expect(hub.postgres.query).toHaveBeenCalledTimes(1)
        })

        it('returns null when no such team', async () => {
            expect(await organizationManager.fetchOrganization(new UUIDT().toString())).toEqual(null)
        })
    })

    describe('hasAvailableFeature()', () => {
        beforeEach(async () => {
            await hub.db.postgres.query(
                PostgresUse.COMMON_WRITE,
                `UPDATE posthog_organization
                 SET available_product_features = array ['{"key": "some_feature", "name": "some_feature"}'::jsonb]`,
                undefined,
                ''
            )
        })

        it('returns if an organization has a feature', async () => {
            expect(await organizationManager.hasAvailableFeature(2, 'some_feature')).toEqual(true)
            expect(await organizationManager.hasAvailableFeature(2, 'another_feature')).toEqual(false)
        })

        it('efficiently uses cached values', async () => {
            // pre-cache the value
            await organizationManager.hasAvailableFeature(2, 'some_feature')

            jest.spyOn(hub.teamManager, 'fetchTeam')
            jest.spyOn(organizationManager, 'fetchOrganization')

            expect(await organizationManager.hasAvailableFeature(2, 'some_feature')).toEqual(true)
            expect(await organizationManager.hasAvailableFeature(2, 'another_feature')).toEqual(false)

            expect(hub.teamManager.fetchTeam).not.toHaveBeenCalled()
            expect(organizationManager.fetchOrganization).not.toHaveBeenCalled()
        })

        it('returns false if team does not exist', async () => {
            expect(await organizationManager.hasAvailableFeature(77, 'some_feature')).toEqual(false)
        })
    })

    describe('resetAvailableFeatureCache()', () => {
        it('resets internal caches', async () => {
            await organizationManager.hasAvailableFeature(2, 'some_feature')

            expect(organizationManager.availableProductFeaturesCache.size).toEqual(1)
            expect(organizationManager.organizationCache.size).toEqual(1)

            organizationManager.resetAvailableProductFeaturesCache(commonOrganizationId)

            expect(organizationManager.availableProductFeaturesCache.size).toEqual(0)
            expect(organizationManager.organizationCache.size).toEqual(0)
        })
    })
})
