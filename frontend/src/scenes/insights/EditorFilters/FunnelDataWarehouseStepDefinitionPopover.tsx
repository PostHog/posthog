import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonButton, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { definitionPopoverLogic } from 'lib/components/DefinitionPopover/definitionPopoverLogic'
import { DatabaseTablePreview } from 'lib/components/TablePreview/DatabaseTablePreview'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { DefinitionPopoverRendererProps, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { DataWarehouseTableForInsight } from 'scenes/data-warehouse/types'

import {
    FunnelFieldKey,
    funnelDataWarehouseStepDefinitionPopoverLogic,
} from './funnelDataWarehouseStepDefinitionPopoverLogic'

type EditableFieldProps = { label: string; shortExplanation: string }

const EDITABLE_FIELD_ORDER: FunnelFieldKey[] = ['distinct_id_field', 'timestamp_field', 'id_field']

const EDITABLE_FIELD_MAP: Record<FunnelFieldKey, EditableFieldProps> = {
    distinct_id_field: {
        label: 'Aggregation target',
        shortExplanation: 'Used to match people or groups across funnel steps.',
    },
    timestamp_field: {
        label: 'Timestamp',
        shortExplanation: 'Used to order step timing and apply the funnel date range.',
    },
    id_field: {
        label: 'Unique ID',
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

    const { selectItem } = useActions(taxonomicFilterLogic)

    const { localDefinition } = useValues(definitionPopoverLogic)

    const dataWarehouseLocalDefinition = localDefinition as Partial<DataWarehouseTableForInsight>
    const selectedItemValue = group.getValue?.(dataWarehouseLocalDefinition) ?? null

    return (
        <div className="flex flex-col gap-3">
            <DatabaseTablePreview table={table} emptyMessage="No table selected" limit={5} />
            <LemonSegmentedButton
                fullWidth
                value={activeFieldKey}
                onChange={(value) => setActiveFieldKey(value as FunnelFieldKey)}
                options={EDITABLE_FIELD_ORDER.map((key) => ({
                    value: key,
                    label: EDITABLE_FIELD_MAP[key].label,
                }))}
            />
            <ActiveField table={table} activeFieldKey={activeFieldKey} {...EDITABLE_FIELD_MAP[activeFieldKey]} />

            <LemonButton
                onClick={() => {
                    selectItem(group, selectedItemValue, dataWarehouseLocalDefinition)
                }}
                type="primary"
            >
                Select
            </LemonButton>
        </div>
    )
}

type ActiveFieldProps = { table: DataWarehouseTableForInsight; activeFieldKey: FunnelFieldKey } & EditableFieldProps

function ActiveField({ table, activeFieldKey, shortExplanation }: ActiveFieldProps): JSX.Element {
    const { localDefinition } = useValues(definitionPopoverLogic)
    const { setLocalDefinition } = useActions(definitionPopoverLogic)

    const dataWarehouseLocalDefinition = localDefinition as Partial<DataWarehouseTableForInsight>
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

    return (
        <div>
            <div className="text-secondary text-xs mb-4">{shortExplanation}</div>
            <LemonSelect
                fullWidth
                value={activeFieldValue}
                options={columnOptions}
                onChange={(value: string | null) =>
                    setLocalDefinition({
                        [activeFieldKey]: value ?? undefined,
                    } as Partial<DataWarehouseTableForInsight>)
                }
            />
        </div>
    )
}
