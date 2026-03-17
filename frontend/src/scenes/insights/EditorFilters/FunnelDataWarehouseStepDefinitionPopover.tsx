import { useActions, useValues } from 'kea'

import { LemonButton, LemonSegmentedButton, LemonSelect, Link } from '@posthog/lemon-ui'

import { HogQLDropdown } from 'lib/components/HogQLDropdown/HogQLDropdown'
import { DatabaseTablePreview } from 'lib/components/TablePreview/DatabaseTablePreview'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { DefinitionPopoverRendererProps, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { DataWarehouseTableForInsight } from 'scenes/data-warehouse/types'
import { urls } from 'scenes/urls'

import { insightLogic } from '../insightLogic'
import {
    FunnelFieldKey,
    funnelDataWarehouseStepDefinitionPopoverLogic,
} from './funnelDataWarehouseStepDefinitionPopoverLogic'

const EDITABLE_FIELD_EXPLANATIONS: Record<FunnelFieldKey, string> = {
    aggregation_target_field: 'Used to match people or groups across funnel steps.',
    timestamp_field: 'Used to order step timing and apply the funnel date range.',
    id_field: 'Used as the unique row ID to detect missing or duplicate records.',
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

    // :FIXME: ideally, we'd want to connect() these, but i couldn't make it work
    const { dataWarehousePopoverFields } = useValues(taxonomicFilterLogic)
    const { selectItem } = useActions(taxonomicFilterLogic)

    const { insightProps } = useValues(insightLogic)

    const logic = funnelDataWarehouseStepDefinitionPopoverLogic({
        table,
        group,
        dataWarehousePopoverFields,
        onSelectItem: selectItem,
        insightProps,
    })
    const {
        activeFieldKey,
        activeFieldKeyOptions,
        activeField,
        activeFieldValue,
        activeFieldOptions,
        activeFieldIsHogQL,
        isAggregatingByGroup,
        isAggregatingByHogQL,
        linkedTables,
        previewTable,
        previewExpressionColumns,
        previewSelectedKey,
    } = useValues(logic)
    const { setActiveFieldKey, selectTable, setLocalDefinition } = useActions(logic)

    return (
        <div className="flex flex-col">
            <DatabaseTablePreview
                table={previewTable}
                selectedKey={previewSelectedKey}
                emptyMessage="No table selected"
                limit={25}
                className="mt-2"
                expressionColumns={previewExpressionColumns}
            />
            <LemonSegmentedButton
                className="mt-4"
                fullWidth
                value={activeFieldKey}
                onChange={(value) => setActiveFieldKey(value as FunnelFieldKey)}
                options={activeFieldKeyOptions}
            />

            <span className="label-text font-semibold mt-3 mb-1">{activeField?.label}</span>
            <div className="text-secondary text-xs">{EDITABLE_FIELD_EXPLANATIONS[activeFieldKey]}</div>

            {activeFieldKey === 'aggregation_target_field' && (
                <div className="text-secondary text-xs mt-1">
                    {isAggregatingByHogQL ? (
                        <span>
                            Current aggregation target is custom. The selected field needs to match the custom
                            aggregation value.
                        </span>
                    ) : (
                        <>
                            <div>
                                Current aggregation target is set to <b>{isAggregatingByGroup ? 'group' : 'person'}</b>,
                                so the selected field needs to match the{' '}
                                <b>{isAggregatingByGroup ? 'Group ID' : 'Person ID'}</b>.
                            </div>
                            <div className="mt-1">
                                If this field is not directly available on the table, add it by joining in{' '}
                                <Link to={urls.sqlEditor()} target="_blank">
                                    SQL editor
                                </Link>{' '}
                                using fields like <code>distinct_id</code> or <code>email</code>.{' '}
                                <Link to="https://posthog.com/docs/data-warehouse/join#table-joins" target="_blank">
                                    For more help
                                </Link>
                                .
                            </div>
                        </>
                    )}
                </div>
            )}

            <LemonSelect
                className="mt-2"
                fullWidth
                value={activeFieldValue}
                options={activeFieldOptions}
                onChange={(value: string | null) =>
                    setLocalDefinition({
                        [activeFieldKey]: value ?? undefined,
                    } as Partial<DataWarehouseTableForInsight>)
                }
            />

            {activeField?.allowHogQL && activeFieldIsHogQL && (
                <HogQLDropdown
                    className="mt-2"
                    hogQLValue={activeFieldValue || ''}
                    tableName={activeField.tableName || table.name}
                    hogQLEditorPlaceholder={
                        linkedTables
                            ? `Enter an SQL Expression, for example:\n- json_column.my_person_id\n- person_distinct_ids.person_id\n\nYou can also reference these linked tables: ${linkedTables.join(', ')}`
                            : `Enter an SQL Expression, for example:\n- json_column.my_person_id\n- person_distinct_ids.person_id`
                    }
                    onHogQLValueChange={(value) =>
                        setLocalDefinition({
                            [activeFieldKey]: value,
                        } as Partial<DataWarehouseTableForInsight>)
                    }
                />
            )}

            <div className="flex justify-end mt-4">
                <LemonButton onClick={selectTable} type="primary">
                    Select
                </LemonButton>
            </div>
        </div>
    )
}
