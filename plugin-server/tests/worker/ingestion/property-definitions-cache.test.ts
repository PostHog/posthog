import { Hub, PropertyDefinitionTypeEnum } from '../../../src/types'
import { closeHub, createHub } from '../../../src/utils/db/hub'
import { PostgresUse } from '../../../src/utils/db/postgres'
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
    let cache: PropertyDefinitionsCache

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()

        cache = new PropertyDefinitionsCache(hub)
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    describe('with pre-existing data', () => {
        beforeEach(async () => {
            await hub.db.postgres.query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO posthog_propertydefinition (id, name, property_type, type, is_numerical, volume_30_day, query_usage_30_day, team_id) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
                [
                    new UUIDT().toString(),
                    'property_name',
                    'String',
                    PropertyDefinitionTypeEnum.Event,
                    false,
                    null,
                    null,
                    2,
                ],
                'testTag'
            )
            await hub.db.postgres.query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO posthog_propertydefinition (id, name, property_type, type, is_numerical, volume_30_day, query_usage_30_day, team_id) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
                [
                    new UUIDT().toString(),
                    'numeric_prop',
                    'String',
                    PropertyDefinitionTypeEnum.Event,
                    true,
                    null,
                    null,
                    2,
                ],
                'testTag'
            )
            await hub.db.postgres.query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO posthog_propertydefinition (id, name, property_type, type, is_numerical, volume_30_day, query_usage_30_day, team_id) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
                [
                    new UUIDT().toString(),
                    'person_prop',
                    'String',
                    PropertyDefinitionTypeEnum.Person,
                    false,
                    null,
                    null,
                    2,
                ],
                'testTag'
            )
            await hub.db.postgres.query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO posthog_propertydefinition (id, name, property_type, type, is_numerical, volume_30_day, query_usage_30_day, team_id, group_type_index) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)`,
                [
                    new UUIDT().toString(),
                    'group_prop',
                    'String',
                    PropertyDefinitionTypeEnum.Group,
                    false,
                    null,
                    null,
                    2,
                    0,
                ],
                'testTag'
            )
        })

        it('initializes cleanly', async () => {
            await cache.initialize(2, hub.db)

            expect(cache.propertyDefinitionsCache.get(2)!.keys()).toEqual(
                expect.arrayContaining(['30group_prop', '2person_prop', '1numeric_prop', '1property_name'])
            )
        })

        it('reports correct shouldUpdate', async () => {
            await cache.initialize(2, hub.db)

            expect(cache.shouldUpdate(2, 'property_name', PropertyDefinitionTypeEnum.Event, null)).toEqual(false)
            expect(cache.shouldUpdate(2, 'numeric_prop', PropertyDefinitionTypeEnum.Event, null)).toEqual(false)
            expect(cache.shouldUpdate(2, 'person_prop', PropertyDefinitionTypeEnum.Person, null)).toEqual(false)
            expect(cache.shouldUpdate(2, 'group_prop', PropertyDefinitionTypeEnum.Group, 0)).toEqual(false)

            expect(cache.shouldUpdate(2, 'new_prop', PropertyDefinitionTypeEnum.Event, null)).toEqual(true)
            expect(cache.shouldUpdate(2, 'new_person_prop', PropertyDefinitionTypeEnum.Person, null)).toEqual(true)
            expect(cache.shouldUpdate(2, 'group_prop', PropertyDefinitionTypeEnum.Group, 1)).toEqual(true)
        })
    })
})
