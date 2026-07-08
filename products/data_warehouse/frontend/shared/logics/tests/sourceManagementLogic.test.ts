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

    it('matches managed sources by display label as well as internal source_type', async () => {
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

        // Display label spelling ("Google ads" with a space) must find the "GoogleAds" source
        logic.actions.setManagedSearchTerm('Google ads')
        await expectLogic(logic).toMatchValues({
            filteredManagedSources: [expect.objectContaining({ source_type: 'GoogleAds' })],
        })

        // Internal source_type spelling still matches
        logic.actions.setManagedSearchTerm('googleads')
        await expectLogic(logic).toMatchValues({
            filteredManagedSources: [expect.objectContaining({ source_type: 'GoogleAds' })],
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
