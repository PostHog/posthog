import { IconInfo, IconTrash } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { DataWarehousePopoverField, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useCallback } from 'react'

import { RevenueTrackingDataWarehouseTable } from '~/queries/schema/schema-general'

import { databaseTableListLogic } from '../database/databaseTableListLogic'
import { revenueEventsSettingsLogic } from './revenueEventsSettingsLogic'

type DataWarehousePopoverFieldKey = 'revenueField' | 'currencyField' | 'timestampField'

// NOTE: Not allowing HogQL right now, but we could add it in the future
const DATA_WAREHOUSE_POPOVER_FIELDS: {
    key: DataWarehousePopoverFieldKey
    label: string
    description: string
    optional?: boolean
}[] = [
    {
        key: 'revenueField' as const,
        label: 'Revenue Field',
        description: 'The revenue amount of the entry.',
    },
    {
        key: 'currencyField' as const,
        label: 'Revenue Currency Field',
        description:
            "The currency code for this revenue entry. E.g. USD, EUR, GBP, etc. If not set, the project's base currency will be used.",
        optional: true,
    },
    {
        key: 'timestampField' as const,
        label: 'Timestamp Field',
        description:
            "The timestamp of the revenue entry. We'll use this to order the revenue entries and properly filter them on Web Analytics.",
    },
] satisfies DataWarehousePopoverField[]

export function DataWarehouseTablesConfiguration({
    buttonRef,
}: {
    buttonRef: React.RefObject<HTMLButtonElement>
}): JSX.Element {
    const { dataWarehouseTables, saveDisabledReason } = useValues(revenueEventsSettingsLogic)
    const { addDataWarehouseTable, deleteDataWarehouseTable, updateDataWarehouseTableColumn, save } =
        useActions(revenueEventsSettingsLogic)

    const { dataWarehouseTablesMap } = useValues(databaseTableListLogic)

    const renderPropertyColumn = useCallback(
        (key: keyof RevenueTrackingDataWarehouseTable) =>
            // eslint-disable-next-line react/display-name
            (_: string | undefined, item: RevenueTrackingDataWarehouseTable) => {
                return (
                    <TaxonomicPopover
                        size="small"
                        className="my-1"
                        allowClear={key === 'revenueCurrencyColumn'}
                        groupType={TaxonomicFilterGroupType.DataWarehouseProperties}
                        onChange={(newValue) => updateDataWarehouseTableColumn(item.tableName, key, newValue)}
                        value={item[key]}
                        schemaColumns={Object.values(dataWarehouseTablesMap?.[item.tableName]?.fields ?? {})}
                        placeholder="Choose column"
                    />
                )
            },
        [dataWarehouseTablesMap, updateDataWarehouseTableColumn]
    )

    return (
        <div>
            <h3 className="mb-2">Data warehouse tables configuration</h3>

            <LemonTable<RevenueTrackingDataWarehouseTable>
                columns={[
                    { key: 'tableName', title: 'Data warehouse table name', dataIndex: 'tableName' },
                    {
                        key: 'revenueColumn',
                        title: 'Revenue column',
                        dataIndex: 'revenueColumn',
                        render: renderPropertyColumn('revenueColumn'),
                    },
                    {
                        key: 'revenueCurrencyColumn',
                        title: (
                            <span>
                                Revenue currency column
                                <Tooltip title="The currency of the revenue entry. If not set, the account's default currency will be used.">
                                    <IconInfo className="ml-1" />
                                </Tooltip>
                            </span>
                        ),
                        dataIndex: 'revenueCurrencyColumn',
                        render: renderPropertyColumn('revenueCurrencyColumn'),
                    },
                    {
                        key: 'timestampColumn',
                        title: 'Revenue timestamp column',
                        dataIndex: 'timestampColumn',
                        render: renderPropertyColumn('timestampColumn'),
                    },
                    {
                        key: 'delete',
                        fullWidth: true,
                        title: (
                            <div className="flex flex-row w-full gap-1 justify-end my-2">
                                <TaxonomicPopover
                                    type="primary"
                                    groupType={TaxonomicFilterGroupType.DataWarehouse}
                                    dataWarehousePopoverFields={DATA_WAREHOUSE_POPOVER_FIELDS}
                                    onChange={(tableName, groupType, properties) => {
                                        // Sanity check, should always be DataWarehouse because we specify above
                                        if (groupType !== TaxonomicFilterGroupType.DataWarehouse) {
                                            return
                                        }

                                        const typedProperties = properties as Record<
                                            DataWarehousePopoverFieldKey,
                                            string
                                        >
                                        addDataWarehouseTable({
                                            tableName: tableName as string,
                                            revenueColumn: typedProperties.revenueField,
                                            revenueCurrencyColumn: typedProperties.currencyField,
                                            timestampColumn: typedProperties.timestampField,
                                        })
                                    }}
                                    value={undefined}
                                    placeholder="Create external data schema"
                                    placeholderClass=""
                                    id="data-management-revenue-settings-add-event"
                                    ref={buttonRef}
                                />

                                <LemonButton type="primary" onClick={save} disabledReason={saveDisabledReason}>
                                    Save
                                </LemonButton>
                            </div>
                        ),
                        render: (_, item) => (
                            <LemonButton
                                className="float-right"
                                size="small"
                                type="secondary"
                                onClick={() => deleteDataWarehouseTable(item.tableName)}
                                icon={<IconTrash />}
                            >
                                Delete
                            </LemonButton>
                        ),
                    },
                ]}
                dataSource={dataWarehouseTables}
                rowKey={(item) => `${item.tableName}-${item.revenueColumn}`}
            />
        </div>
    )
}
