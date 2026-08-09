import { expectLogic } from 'kea-test-utils'

import api, { PaginatedResponse } from 'lib/api'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { performQuery } from '~/queries/query'
import { DatabaseSchemaQueryResponse } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ExternalDataSource } from '~/types'

import { availableSourcesLogic } from '../../../scenes/NewSourceScene/availableSourcesLogic'
import { sourceManagementLogic } from '../sourceManagementLogic'

jest.mock('lib/api')
jest.mock('~/queries/query')

describe('sourceManagementLogic', () => {
    let logic: ReturnType<typeof sourceManagementLogic.build>
    let databaseLogic: ReturnType<typeof databaseTableListLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = sourceManagementLogic()
        databaseLogic = databaseTableListLogic()

        jest.spyOn(api.externalDataSources, 'list').mockResolvedValue({
            results: [],
            count: 0,
            next: null,
            previous: null,
        } as PaginatedResponse<ExternalDataSource>)
        jest.spyOn(api.dataWarehouseViewLinks, 'list').mockResolvedValue({
            results: [],
        } as any)

        ;(performQuery as jest.Mock).mockResolvedValue({
            tables: {},
            joins: [],
        } as DatabaseSchemaQueryResponse)
    })

    afterEach(() => {
        logic.unmount()
        databaseLogic.unmount()
    })

    it.each([
        ['display label', 'Google ads'],
        ['internal source_type', 'googleads'],
    ])('finds a managed source by its %s', async (_, searchTerm) => {
        jest.spyOn(api.externalDataSources, 'wizard').mockResolvedValue({
            GoogleAds: { name: 'GoogleAds', label: 'Google Ads' },
        } as any)

        logic.mount()
        await expectLogic(availableSourcesLogic).toDispatchActions(['loadSuccess'])

        sourceManagementLogic.actions.loadSourcesSuccess({
            results: [{ id: 's1', source_type: 'GoogleAds', access_method: 'warehouse', schemas: [] }],
            count: 1,
            next: null,
            previous: null,
        } as any)

        logic.actions.setManagedSearchTerm(searchTerm)
        await expectLogic(logic).toMatchValues({
            filteredManagedSources: [expect.objectContaining({ source_type: 'GoogleAds' })],
        })
    })

    it('lists direct connect sources separately from managed ones', async () => {
        logic.mount()

        sourceManagementLogic.actions.loadSourcesSuccess({
            results: [
                { id: 's1', source_type: 'Stripe', access_method: 'warehouse', schemas: [] },
                { id: 's2', source_type: 'Postgres', prefix: 'prod', access_method: 'direct', schemas: [] },
                { id: 's3', source_type: 'Snowflake', prefix: 'analytics', access_method: 'direct', schemas: [] },
            ],
            count: 3,
            next: null,
            previous: null,
        } as any)

        await expectLogic(logic).toMatchValues({
            managedSources: [expect.objectContaining({ id: 's1' })],
            directSources: [expect.objectContaining({ id: 's2' }), expect.objectContaining({ id: 's3' })],
        })

        logic.actions.setDirectSearchTerm('analytics')
        await expectLogic(logic).toMatchValues({
            filteredDirectSources: [expect.objectContaining({ id: 's3' })],
        })
    })

    it('only includes tables with no source in selfManagedTables', async () => {
        databaseLogic.mount()
        logic.mount()
        databaseTableListLogic.actions.loadDatabaseSuccess({
            tables: {
                no_source_table: {
                    id: 'no-source',
                    type: 'data_warehouse',
                    name: 'no_source_table',
                    fields: {},
                    format: 'Parquet',
                    url_pattern: 'https://bucket/path/*.parquet',
                },
                direct_source_table: {
                    id: 'with-direct-source',
                    type: 'data_warehouse',
                    name: 'direct_source_table',
                    fields: {},
                    format: 'Parquet',
                    url_pattern: 'direct://table',
                    source: {
                        id: 'source-1',
                        status: 'Running',
                        source_type: 'Postgres',
                        prefix: 'prod',
                        access_method: 'direct',
                    },
                },
                warehouse_source_table: {
                    id: 'with-warehouse-source',
                    type: 'data_warehouse',
                    name: 'warehouse_source_table',
                    fields: {},
                    format: 'Parquet',
                    url_pattern: 'warehouse://table',
                    source: {
                        id: 'source-2',
                        status: 'Running',
                        source_type: 'Snowflake',
                        prefix: 'dw',
                        access_method: 'warehouse',
                    },
                },
            },
            joins: [],
        } as DatabaseSchemaQueryResponse)

        await expectLogic(logic).toMatchValues({
            selfManagedTables: [
                expect.objectContaining({
                    name: 'no_source_table',
                }),
            ],
        })
    })
})
