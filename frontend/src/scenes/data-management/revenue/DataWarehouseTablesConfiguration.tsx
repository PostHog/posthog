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
import { CurrencyDropdown } from './CurrencyDropdown'
import { revenueEventsSettingsLogic } from './revenueEventsSettingsLogic'

type DataWarehousePopoverFieldKey = 'revenueField' | 'currencyField' | 'timestampField' | 'distinctIdColumn'

// NOTE: Not allowing HogQL right now, but we could add it in the future
const DATA_WAREHOUSE_POPOVER_FIELDS: {
    key: DataWarehousePopoverFieldKey
    label: string
    description: string
    optional?: boolean
}[] = [
    {
        key: 'distinctIdColumn' as const,
        label: 'Distinct ID Column',
        description: 'The distinct ID column in your table that uniquely identifies a row.',
    },
    {
        key: 'timestampField' as const,
        label: 'Timestamp Field',
        description:
            "The timestamp of the revenue entry. We'll use this to order the revenue entries and properly filter them on Web Analytics.",
    },
    {
        key: 'revenueField' as const,
        label: 'Revenue Field',
        description: 'The revenue amount of the entry.',
    },
    {
        key: 'currencyField' as const,
        label: 'Revenue Currency Field',
        description:
            "The currency code for this revenue entry. E.g. USD, EUR, GBP, etc. If not set, you'll be able to choose a static currency for all entries in this table.",
        optional: true,
    },
] satisfies DataWarehousePopoverField[]

export function DataWarehouseTablesConfiguration({
    buttonRef,
}: {
    buttonRef: React.RefObject<HTMLButtonElement>
}): JSX.Element {
    const {
        baseCurrency,
        dataWarehouseTables,
        saveDataWarehouseTablesDisabledReason,
        changesMadeToDataWarehouseTables,
    } = useValues(revenueEventsSettingsLogic)
    const {
        addDataWarehouseTable,
        deleteDataWarehouseTable,
        updateDataWarehouseTableColumn,
        updateDataWarehouseTableRevenueCurrencyColumn,
        save,
    } = useActions(revenueEventsSettingsLogic)

    const { dataWarehouseTablesMap } = useValues(databaseTableListLogic)

    // Restricting to timestampColumn and revenueColumn because currency column
    // is slightly more complicated than that
    const renderPropertyColumn = useCallback(
        (key: keyof RevenueTrackingDataWarehouseTable & ('timestampColumn' | 'revenueColumn' | 'distinctIdColumn')) =>
            // eslint-disable-next-line react/display-name
            (_: any, item: RevenueTrackingDataWarehouseTable) => {
                return (
                    <TaxonomicPopover
                        size="small"
                        className="my-1"
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
                        key: 'distinctIdColumn',
                        title: (
                            <span>
                                Distinct ID column
                                <Tooltip title="The distinct ID column in your table that uniquely identifies a row.">
                                    <IconInfo className="ml-1" />
                                </Tooltip>
                            </span>
                        ),
                        dataIndex: 'distinctIdColumn',
                        render: renderPropertyColumn('distinctIdColumn'),
                    },
                    {
                        key: 'timestampColumn',
                        title: (
                            <span>
                                Timestamp column
                                <Tooltip title="The timestamp column in your table that identifies when the revenue entry was created. We'll use this to order the revenue entries and properly filter them by timestamp.">
                                    <IconInfo className="ml-1" />
                                </Tooltip>
                            </span>
                        ),
                        dataIndex: 'timestampColumn',
                        render: renderPropertyColumn('timestampColumn'),
                    },
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
                                <Tooltip title="The currency of this revenue entry in your table. You can choose between a column on your table OR a hardcoded currency.">
                                    <IconInfo className="ml-1" />
                                </Tooltip>
                            </span>
                        ),
                        dataIndex: 'revenueCurrencyColumn',
                        render: (_, item: RevenueTrackingDataWarehouseTable) => {
                            return (
                                <div className="flex flex-col w-full gap-3 my-1 min-w-[250px] whitespace-nowrap">
                                    <div className="flex flex-row gap-1">
                                        <span className="font-bold">Dynamic column: </span>
                                        <TaxonomicPopover
                                            size="small"
                                            groupType={TaxonomicFilterGroupType.DataWarehouseProperties}
                                            onChange={(newValue) =>
                                                updateDataWarehouseTableRevenueCurrencyColumn(item.tableName, {
                                                    property: newValue!,
                                                })
                                            }
                                            value={item.revenueCurrencyColumn.property ?? null}
                                            schemaColumns={Object.values(
                                                dataWarehouseTablesMap?.[item.tableName]?.fields ?? {}
                                            )}
                                            placeholder="Choose column"
                                        />
                                    </div>
                                    <div className="flex flex-row gap-1">
                                        or <span className="font-bold">Static currency: </span>
                                        <CurrencyDropdown
                                            size="small"
                                            onChange={(currency) =>
                                                updateDataWarehouseTableRevenueCurrencyColumn(item.tableName, {
                                                    static: currency!,
                                                })
                                            }
                                            value={item.revenueCurrencyColumn.static ?? null}
                                        />
                                    </div>
                                </div>
                            )
                        },
                    },
                    {
                        key: 'delete',
                        fullWidth: true,
                        title: (
                            <div className="flex flex-col gap-1 items-end w-full">
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
                                                distinctIdColumn: typedProperties.distinctIdColumn,
                                                revenueCurrencyColumn: typedProperties.currencyField
                                                    ? { property: typedProperties.currencyField }
                                                    : { static: baseCurrency },
                                                timestampColumn: typedProperties.timestampField,
                                            })
                                        }}
                                        value={undefined}
                                        placeholder="Create external data schema"
                                        placeholderClass=""
                                        id="data-management-revenue-settings-add-event"
                                        ref={buttonRef}
                                    />

                                    <LemonButton
                                        type="primary"
                                        onClick={save}
                                        disabledReason={saveDataWarehouseTablesDisabledReason}
                                    >
                                        Save
                                    </LemonButton>
                                </div>
                                {changesMadeToDataWarehouseTables && (
                                    <span className="text-xs text-error normal-case font-normal">
                                        Remember to save your changes
                                    </span>
                                )}
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
