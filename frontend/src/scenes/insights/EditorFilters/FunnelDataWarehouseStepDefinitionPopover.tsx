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

    const { taxonomicFilterLogicKey } = useValues(taxonomicFilterLogic)
    const { insightProps } = useValues(insightLogic)

    const logic = funnelDataWarehouseStepDefinitionPopoverLogic({
        table: item as DataWarehouseTableForInsight,
        group,
        taxonomicFilterLogicKey,
        insightProps,
    })
    const {
        activeFieldKey,
        activeField,
        activeFieldValue,
        activeFieldOptions,
        activeFieldIsHogQL,
        dataWarehousePopoverFields,
        isAggregatingByGroup,
        isAggregatingByHogQL,
    } = useValues(logic)
    const { setActiveFieldKey, selectTable, setLocalDefinition } = useActions(logic)

    return (
        <div className="flex flex-col">
            <DatabaseTablePreview
                table={table}
                selectedKey={activeFieldValue}
                emptyMessage="No table selected"
                limit={5}
                className="mt-2"
            />
            <LemonSegmentedButton
                className="mt-4"
                fullWidth
                value={activeFieldKey}
                onChange={(value) => setActiveFieldKey(value as FunnelFieldKey)}
                options={EDITABLE_FIELD_ORDER.map((key) => ({
                    value: key,
                    label: dataWarehousePopoverFields.find((f) => f.key === key)?.label ?? key,
                }))}
            />

            <span className="label-text font-semibold mt-3 mb-1">{activeField?.label}</span>
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

            {activeField?.allowHogQL && activeFieldIsHogQL && (
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
                                <b>{isAggregatingByGroup ? 'group ID' : 'person ID'}</b>.
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
                <LemonButton onClick={selectTable} type="primary">
                    Select
                </LemonButton>
            </div>
        </div>
    )
}
