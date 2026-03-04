import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonButton, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { definitionPopoverLogic } from 'lib/components/DefinitionPopover/definitionPopoverLogic'
import { HogQLDropdown } from 'lib/components/HogQLDropdown/HogQLDropdown'
import { DatabaseTablePreview } from 'lib/components/TablePreview/DatabaseTablePreview'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { DefinitionPopoverRendererProps, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { DataWarehouseTableForInsight } from 'scenes/data-warehouse/types'

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

    return (
        <div className="flex flex-col gap-3">
            <DatabaseTablePreview table={table} emptyMessage="No table selected" limit={5} />
            <LemonSegmentedButton
                fullWidth
                value={activeFieldKey}
                onChange={(value) => setActiveFieldKey(value as FunnelFieldKey)}
                options={EDITABLE_FIELD_ORDER.map((key) => ({
                    value: key,
                    label: dataWarehousePopoverFields.find((f) => f.key === key).label,
                }))}
            />

            <div className="text-secondary text-xs">{EDITABLE_FIELD_MAP[activeFieldKey].shortExplanation}</div>
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
                    hogQLValue={activeFieldValue || ''}
                    tableName={activeField.tableName || table.name}
                    onHogQLValueChange={(value) =>
                        setLocalDefinition({
                            [activeFieldKey]: value,
                        } as Partial<DataWarehouseTableForInsight>)
                    }
                />
            )}

            <LemonButton
                onClick={() => {
                    selectItem(group, table.name, dataWarehouseLocalDefinition)
                }}
                type="primary"
            >
                Select
            </LemonButton>
        </div>
    )
}
