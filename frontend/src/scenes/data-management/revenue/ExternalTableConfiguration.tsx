import { IconInfo, IconTrash } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { DataWarehousePopoverField, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useCallback } from 'react'

import { RevenueTrackingExternalDataSchema } from '~/queries/schema/schema-general'

import { databaseTableListLogic } from '../database/databaseTableListLogic'
import { revenueEventsSettingsLogic } from './revenueEventsSettingsLogic'

// NOTE: Not allowing HogQL right now, but we could add it in the future
const DATA_WAREHOUSE_POPOVER_FIELDS = [
    {
        key: 'revenueField',
        label: 'Revenue Field',
        description: 'The revenue amount of the entry.',
    },
    {
        key: 'currencyField',
        label: 'Revenue Currency Field',
        description:
            "The currency code for this revenue entry. E.g. USD, EUR, GBP, etc. If not set, the project's base currency will be used.",
        optional: true,
    },
    {
        key: 'timestampField',
        label: 'Timestamp Field',
        description:
            "The timestamp of the revenue entry. We'll use this to order the revenue entries and properly filter them on Web Analytics.",
    },
] as const satisfies DataWarehousePopoverField[]

type DataWarehouseInformationField = (typeof DATA_WAREHOUSE_POPOVER_FIELDS)[number]['key']

export function ExternalTableConfiguration({
    buttonRef,
}: {
    buttonRef: React.RefObject<HTMLButtonElement>
}): JSX.Element {
    const { externalDataSchemas, saveDisabledReason } = useValues(revenueEventsSettingsLogic)
    const { addExternalDataSchema, deleteExternalDataSchema, updateExternalDataSchemaColumn, save } =
        useActions(revenueEventsSettingsLogic)

    const { dataWarehouseTablesMap } = useValues(databaseTableListLogic)

    const renderPropertyColumn = useCallback(
        (key: keyof RevenueTrackingExternalDataSchema) =>
            // eslint-disable-next-line react/display-name
            (_: string | undefined, item: RevenueTrackingExternalDataSchema) => {
                return (
                    <TaxonomicPopover
                        size="small"
                        className="my-1"
                        allowClear={key === 'revenueCurrencyColumn'}
                        groupType={TaxonomicFilterGroupType.DataWarehouseProperties}
                        onChange={(newValue) => updateExternalDataSchemaColumn(item.tableName, key, newValue)}
                        value={item[key]}
                        schemaColumns={Object.values(dataWarehouseTablesMap?.[item.tableName]?.fields ?? {})}
                        placeholder="Choose column"
                    />
                )
            },
        [dataWarehouseTablesMap, updateExternalDataSchemaColumn]
    )

    return (
        <div>
            <h3 className="mb-2">External table configuration</h3>

            <LemonTable<RevenueTrackingExternalDataSchema>
                columns={[
                    { key: 'tableName', title: 'External table name', dataIndex: 'tableName' },
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
                                            DataWarehouseInformationField,
                                            string
                                        >
                                        addExternalDataSchema({
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
                                onClick={() => deleteExternalDataSchema(item.tableName)}
                                icon={<IconTrash />}
                            >
                                Delete
                            </LemonButton>
                        ),
                    },
                ]}
                dataSource={externalDataSchemas}
                rowKey={(item) => `${item.tableName}-${item.revenueColumn}`}
            />
        </div>
    )
}
