import { connect, kea, key, path, props, selectors } from 'kea'

import { IconServer } from '@posthog/icons'

import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
} from 'lib/components/TaxonomicFilter/types'
import { dataWarehouseSettingsSceneLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsSceneLogic'

import { DatabaseSchemaField, DatabaseSchemaTable } from '~/queries/schema/schema-general'
import { PersonProperty } from '~/types'

import { joinsLogic } from 'products/data_warehouse/frontend/shared/logics/joinsLogic'

import type { dataWarehouseTaxonomicGroupsLogicType } from './dataWarehouseTaxonomicGroupsLogicType'

export const dataWarehouseTaxonomicGroupsLogic = kea<dataWarehouseTaxonomicGroupsLogicType>([
    props({} as TaxonomicFilterLogicProps),
    key((props) => `${props.taxonomicFilterLogicKey}`),
    path((key) => ['lib', 'components', 'TaxonomicFilter', 'dataWarehouseTaxonomicGroupsLogic', key]),

    connect(() => ({
        values: [
            dataWarehouseSettingsSceneLogic, // This logic needs to be connected to stop the popover from erroring out
            ['dataWarehouseTables'],
            joinsLogic,
            ['columnsJoinedToPersons'],
        ],
    })),

    selectors({
        schemaColumns: [
            () => [(_, props) => props.schemaColumns],
            (schemaColumns): DatabaseSchemaField[] => schemaColumns ?? [],
        ],
        schemaColumnsLoading: [
            () => [(_, props) => props.schemaColumnsLoading],
            (schemaColumnsLoading: boolean | undefined) => !!schemaColumnsLoading,
        ],
        dataWarehouseTaxonomicGroups: [
            (s) => [s.schemaColumns, s.schemaColumnsLoading],
            (schemaColumns, schemaColumnsLoading): TaxonomicFilterGroup[] => [
                {
                    name: 'Data warehouse tables',
                    searchPlaceholder: 'data warehouse tables',
                    type: TaxonomicFilterGroupType.DataWarehouse,
                    logic: dataWarehouseSettingsSceneLogic,
                    value: 'dataWarehouseTablesAndViews',
                    valueLoading: 'databaseLoading',
                    getName: (table: DatabaseSchemaTable) => table.name,
                    getValue: (table: DatabaseSchemaTable) => table.name,
                    getPopoverHeader: () => 'Data Warehouse Table',
                    getIcon: () => <IconServer />,
                },
                ...(schemaColumns.length > 0 || schemaColumnsLoading
                    ? [
                          {
                              name: 'Data warehouse properties',
                              searchPlaceholder: 'data warehouse properties',
                              type: TaxonomicFilterGroupType.DataWarehouseProperties,
                              options: schemaColumns,
                              getName: (col: DatabaseSchemaField) => col.name,
                              getValue: (col: DatabaseSchemaField) => col.name,
                              getPopoverHeader: () => 'Data Warehouse Column',
                              getIcon: () => <IconServer />,
                          } as TaxonomicFilterGroup,
                      ]
                    : []),
                {
                    name: 'Extended person properties',
                    searchPlaceholder: 'extended person properties',
                    type: TaxonomicFilterGroupType.DataWarehousePersonProperties,
                    logic: joinsLogic,
                    value: 'columnsJoinedToPersons',
                    getName: (personProperty: PersonProperty) => personProperty.name,
                    getValue: (personProperty: PersonProperty) => personProperty.id,
                    getPopoverHeader: () => 'Extended Person Property',
                },
            ],
        ],
    }),
])
