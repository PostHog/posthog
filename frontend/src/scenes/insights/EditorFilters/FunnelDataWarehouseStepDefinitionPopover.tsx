import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonButton, LemonSegmentedButton, LemonSelect, Link } from '@posthog/lemon-ui'

import { definitionPopoverLogic } from 'lib/components/DefinitionPopover/definitionPopoverLogic'
import { HogQLDropdown } from 'lib/components/HogQLDropdown/HogQLDropdown'
import { DatabaseTablePreview } from 'lib/components/TablePreview/DatabaseTablePreview'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { DefinitionPopoverRendererProps, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { DataWarehouseTableForInsight } from 'scenes/data-warehouse/types'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { urls } from 'scenes/urls'

import { insightLogic } from '../insightLogic'
import {
    FunnelFieldKey,
    funnelDataWarehouseStepDefinitionPopoverLogic,
} from './funnelDataWarehouseStepDefinitionPopoverLogic'

function isUsingHogQLExpression(fieldValue: string | undefined, table: DataWarehouseTableForInsight): boolean {
    if (fieldValue === undefined) {
        return false
    }
    return !Object.values(table.fields).some((field) => field.name === fieldValue)
}

type EditableFieldProps = { shortExplanation: string }

const EDITABLE_FIELD_ORDER: FunnelFieldKey[] = ['distinct_id_field', 'timestamp_field', 'id_field']

const EDITABLE_FIELD_MAP: Record<FunnelFieldKey, EditableFieldProps> = {
    distinct_id_field: {
        shortExplanation: 'Used to match people or groups across funnel steps.',
    },
    timestamp_field: {
        shortExplanation: 'Used to order step timing and apply the funnel date range.',
    },
    id_field: {
        shortExplanation: 'Used as the unique row ID to detect missing or duplicate records.',
    },
}

export function FunnelDataWarehouseStepDefinitionPopover({
    item,
    group,
    defaultView,
}: DefinitionPopoverRendererProps): JSX.Element {
    if (group.type !== TaxonomicFilterGroupType.DataWarehouse) {
        return defaultView
    }

    return <FunnelDataWarehouseStepDefinitionPopoverContent item={item} group={group} />
}

function FunnelDataWarehouseStepDefinitionPopoverContent({
    item,
    group,
}: Omit<DefinitionPopoverRendererProps, 'defaultView'>): JSX.Element {
    const table = item as DataWarehouseTableForInsight

    const { activeFieldKey } = useValues(funnelDataWarehouseStepDefinitionPopoverLogic({ tableName: table.name }))
    const { setActiveFieldKey } = useActions(funnelDataWarehouseStepDefinitionPopoverLogic({ tableName: table.name }))

    const { dataWarehousePopoverFields } = useValues(taxonomicFilterLogic)
    const { selectItem } = useActions(taxonomicFilterLogic)

    const { localDefinition } = useValues(definitionPopoverLogic)
    const { setLocalDefinition } = useActions(definitionPopoverLogic)

    const { insightProps } = useValues(insightLogic)
    const { querySource } = useValues(funnelDataLogic(insightProps))

    const dataWarehouseLocalDefinition = localDefinition as Partial<DataWarehouseTableForInsight>

    const activeField = dataWarehousePopoverFields.find((f) => f.key === activeFieldKey)
    const activeFieldValue = dataWarehouseLocalDefinition[activeFieldKey]

    const columnOptions = useMemo(
        () =>
            Object.values(table.fields).map((column) => ({
                label: `${column.name} (${column.type})`,
                value: column.name,
                type: column.type,
            })),
        [table.fields]
    )
    const activeFieldOptions = useMemo(() => {
        return [
            ...columnOptions.filter((column) => !activeField.type || column.type === activeField.type),
            ...(activeField.allowHogQL ? [{ label: 'SQL Expression', value: '' }] : []),
        ]
    }, [activeField, columnOptions])

    const activeFieldIsHogQL = isUsingHogQLExpression(activeFieldValue, table)

    const isGroupAggregationTarget =
        querySource?.aggregation_group_type_index !== undefined && querySource?.aggregation_group_type_index !== null
    const isCustomAggregationTarget =
        Boolean(querySource?.funnelsFilter?.funnelAggregateByHogQL) && !isGroupAggregationTarget
    const aggregationTargetIdLabel = isGroupAggregationTarget ? 'group ID' : 'person ID'

    return (
        <div className="flex flex-col">
            <DatabaseTablePreview table={table} emptyMessage="No table selected" limit={5} className="mt-2" />
            <LemonSegmentedButton
                className="mt-4"
                fullWidth
                value={activeFieldKey}
                onChange={(value) => setActiveFieldKey(value as FunnelFieldKey)}
                options={EDITABLE_FIELD_ORDER.map((key) => ({
                    value: key,
                    label: dataWarehousePopoverFields.find((f) => f.key === key).label,
                }))}
            />

            <span className="label-text font-semibold mt-3 mb-1">{activeField.label}</span>
            <div className="text-secondary text-xs mb-3">{EDITABLE_FIELD_MAP[activeFieldKey].shortExplanation}</div>

            <LemonSelect
                fullWidth
                value={activeFieldValue}
                options={activeFieldOptions}
                onChange={(value: string | null) =>
                    setLocalDefinition({
                        [activeFieldKey]: value ?? undefined,
                    } as Partial<DataWarehouseTableForInsight>)
                }
            />

            {activeField.allowHogQL && activeFieldIsHogQL && (
                <HogQLDropdown
                    className="mt-2"
                    hogQLValue={activeFieldValue || ''}
                    tableName={activeField.tableName || table.name}
                    onHogQLValueChange={(value) =>
                        setLocalDefinition({
                            [activeFieldKey]: value,
                        } as Partial<DataWarehouseTableForInsight>)
                    }
                />
            )}

            {activeFieldKey === 'distinct_id_field' && (
                <div className="text-secondary text-xs mt-2">
                    {isCustomAggregationTarget ? (
                        <span>
                            Current aggregation target is custom. The selected field needs to match the custom
                            aggregation value.
                        </span>
                    ) : (
                        <>
                            <div>
                                Current aggregation target is set to{' '}
                                <b>{isGroupAggregationTarget ? 'group' : 'person'}</b>, so the selected field needs to
                                match the <b>{aggregationTargetIdLabel}</b>.
                            </div>
                            <div className="mt-1">
                                If this field is not directly available on the table, add it by joining in{' '}
                                <Link to={urls.sqlEditor()} target="_blank">
                                    SQL editor
                                </Link>{' '}
                                using fields like <code>distinct_id</code> or <code>email</code>.{' '}
                                <Link to="https://posthog.com/docs/data-warehouse/views#joining-tables" target="_blank">
                                    For more help
                                </Link>
                                .
                            </div>
                        </>
                    )}
                </div>
            )}

            <div className="flex justify-end mt-4">
                <LemonButton
                    onClick={() => {
                        selectItem(group, table.name, dataWarehouseLocalDefinition)
                    }}
                    type="primary"
                >
                    Select
                </LemonButton>
            </div>
        </div>
    )
}
