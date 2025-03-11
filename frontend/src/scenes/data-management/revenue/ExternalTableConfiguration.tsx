import { IconInfo, IconTrash } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useCallback } from 'react'

import { RevenueTrackingExternalDataSchema } from '~/queries/schema/schema-general'

import { revenueEventsSettingsLogic } from './revenueEventsSettingsLogic'

export function ExternalTableConfiguration({
    buttonRef,
}: {
    buttonRef: React.RefObject<HTMLButtonElement>
}): JSX.Element {
    const { externalDataSchemas, saveDisabledReason } = useValues(revenueEventsSettingsLogic)
    const {
        addExternalDataSchema,
        deleteExternalDataSchema,
        updateExternalDataSchemaRevenueColumn,
        updateExternalDataSchemaRevenueCurrencyColumn,
        save,
    } = useActions(revenueEventsSettingsLogic)

    const renderPropertyColumn = useCallback(
        (
                key: keyof RevenueTrackingExternalDataSchema,
                updatePropertyFunction: (externalDataSchemaName: string, propertyName: string) => void
            ) =>
            // eslint-disable-next-line react/display-name
            (_: string | undefined, item: RevenueTrackingExternalDataSchema) => {
                return (
                    <TaxonomicPopover
                        showNumericalPropsOnly
                        size="small"
                        className="my-1"
                        groupType={TaxonomicFilterGroupType.DataWarehouseProperties}
                        onChange={(newPropertyName) => updatePropertyFunction(item.name, newPropertyName)}
                        value={item[key]}
                        placeholder="Choose column"
                    />
                )
            },
        []
    )

    return (
        <div>
            <h3 className="mb-2">External table configuration</h3>

            <LemonTable<RevenueTrackingExternalDataSchema>
                columns={[
                    { key: 'name', title: 'External table name', dataIndex: 'name' },
                    {
                        key: 'revenueColumn',
                        title: 'Revenue column',
                        dataIndex: 'revenueColumn',
                        render: renderPropertyColumn('revenueColumn', updateExternalDataSchemaRevenueColumn),
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
                        render: renderPropertyColumn(
                            'revenueCurrencyColumn',
                            updateExternalDataSchemaRevenueCurrencyColumn
                        ),
                    },
                    {
                        key: 'delete',
                        fullWidth: true,
                        title: (
                            <div className="flex flex-row w-full gap-1 justify-end my-2">
                                <TaxonomicPopover
                                    type="primary"
                                    groupType={TaxonomicFilterGroupType.DataWarehouse}
                                    onChange={addExternalDataSchema}
                                    value={undefined}
                                    placeholder="Create external data schema"
                                    placeholderClass=""
                                    excludedProperties={{
                                        [TaxonomicFilterGroupType.DataWarehouse]: [
                                            null,
                                            ...externalDataSchemas.map((item) => item.name),
                                        ],
                                    }}
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
                                onClick={() => deleteExternalDataSchema(item.name)}
                                icon={<IconTrash />}
                            >
                                Delete
                            </LemonButton>
                        ),
                    },
                ]}
                dataSource={externalDataSchemas}
                rowKey={(item) => item.name}
            />
        </div>
    )
}
