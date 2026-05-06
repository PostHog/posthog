import { expectLogic } from 'kea-test-utils'

import api, { PaginatedResponse } from 'lib/api'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { performQuery } from '~/queries/query'
import { DatabaseSchemaQueryResponse } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ExternalDataSource } from '~/types'

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
