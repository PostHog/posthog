import { Hub, PropertyDefinitionTypeEnum } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { UUIDT } from '../../../src/utils/utils'
import { PropertyDefinitionsCache } from '../../../src/worker/ingestion/property-definitions-cache'
import { resetTestDatabase } from '../../helpers/sql'

jest.mock('../../../src/utils/status')
jest.mock('../../../src/utils/posthog', () => ({
    posthog: {
        identify: jest.fn(),
        capture: jest.fn(),
    },
}))

describe('PropertyDefinitionsManager()', () => {
    let hub: Hub
    let closeHub: () => Promise<void>
    let cache: PropertyDefinitionsCache
    let teamId: number

    beforeAll(async () => {
        ;[hub, closeHub] = await createHub()
    })

    beforeEach(async () => {
        ;({ teamId } = await resetTestDatabase())

        cache = new PropertyDefinitionsCache(hub)
    })

    afterAll(async () => {
        await closeHub()
    })

    describe('with pre-existing data', () => {
        beforeEach(async () => {
            await hub.db.postgresQuery(
                `INSERT INTO posthog_propertydefinition (id, name, property_type, type, is_numerical, volume_30_day, query_usage_30_day, team_id) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
                [
                    new UUIDT().toString(),
                    'property_name',
                    'String',
                    PropertyDefinitionTypeEnum.Event,
                    false,
                    null,
                    null,
                    teamId,
                ],
                'testTag'
            )
            await hub.db.postgresQuery(
                `INSERT INTO posthog_propertydefinition (id, name, property_type, type, is_numerical, volume_30_day, query_usage_30_day, team_id) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
                [
                    new UUIDT().toString(),
                    'numeric_prop',
                    'String',
                    PropertyDefinitionTypeEnum.Event,
                    true,
                    null,
                    null,
                    teamId,
                ],
                'testTag'
            )
            await hub.db.postgresQuery(
                `INSERT INTO posthog_propertydefinition (id, name, property_type, type, is_numerical, volume_30_day, query_usage_30_day, team_id) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
                [
                    new UUIDT().toString(),
                    'person_prop',
                    'String',
                    PropertyDefinitionTypeEnum.Person,
                    false,
                    null,
                    null,
                    teamId,
                ],
                'testTag'
            )
            await hub.db.postgresQuery(
                `INSERT INTO posthog_propertydefinition (id, name, property_type, type, is_numerical, volume_30_day, query_usage_30_day, team_id, group_type_index) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)`,
                [
                    new UUIDT().toString(),
                    'group_prop',
                    'String',
                    PropertyDefinitionTypeEnum.Group,
                    false,
                    null,
                    null,
                    teamId,
                    0,
                ],
                'testTag'
            )
        })

        it('initializes cleanly', async () => {
            await cache.initialize(teamId, hub.db)

            expect(cache.propertyDefinitionsCache.get(teamId)!.keys()).toEqual(
                expect.arrayContaining(['30group_prop', '2person_prop', '1numeric_prop', '1property_name'])
            )
        })

        it('reports correct shouldUpdate', async () => {
            await cache.initialize(teamId, hub.db)

            expect(cache.shouldUpdate(teamId, 'property_name', PropertyDefinitionTypeEnum.Event, null)).toEqual(false)
            expect(cache.shouldUpdate(teamId, 'numeric_prop', PropertyDefinitionTypeEnum.Event, null)).toEqual(false)
            expect(cache.shouldUpdate(teamId, 'person_prop', PropertyDefinitionTypeEnum.Person, null)).toEqual(false)
            expect(cache.shouldUpdate(teamId, 'group_prop', PropertyDefinitionTypeEnum.Group, 0)).toEqual(false)

            expect(cache.shouldUpdate(teamId, 'new_prop', PropertyDefinitionTypeEnum.Event, null)).toEqual(true)
            expect(cache.shouldUpdate(teamId, 'new_person_prop', PropertyDefinitionTypeEnum.Person, null)).toEqual(true)
            expect(cache.shouldUpdate(teamId, 'group_prop', PropertyDefinitionTypeEnum.Group, 1)).toEqual(true)
        })
    })
})
