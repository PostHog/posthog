import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo, useState } from 'react'

import { IconBookmark, IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'
import { urls } from 'scenes/urls'

import { CoreEvent, DataWarehouseNode, NodeKind, SchemaMap } from '~/queries/schema/schema-general'

import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { getGoalFilterSummary, getGoalTypeLabel, getTableColumns } from '../../utils/coreEventUtils'
import { SchemaMapModal } from '../SchemaMapModal'

const DEFINE_NEW_CORE_EVENT = '__define_new_core_event__'

const DEFAULT_SCHEMA_MAP: SchemaMap = {
    utm_campaign_name: 'utm_campaign',
    utm_source_name: 'utm_source',
    timestamp_field: undefined,
    distinct_id_field: undefined,
}

interface SchemaMapFormState {
    goal: CoreEvent
    schemaMap: SchemaMap
    isSaving: boolean // true when saving to mapping, false when just exploring
}

export function ExploreCoreEventDropdown(): JSX.Element {
    const { draftConversionGoal, availableCoreEventsForExplore } = useValues(marketingAnalyticsLogic)
    const { setDraftConversionGoal, clearConversionGoal, addGoalMapping } = useActions(marketingAnalyticsLogic)
    const { dataWarehouseTables } = useValues(dataWarehouseSettingsLogic)

    const [schemaMapForm, setSchemaMapForm] = useState<SchemaMapFormState | null>(null)

    // Get available columns for the current goal's table
    const availableColumns = useMemo(() => {
        if (!schemaMapForm?.goal) {
            return []
        }
        return getTableColumns(schemaMapForm.goal, dataWarehouseTables || [])
    }, [schemaMapForm?.goal, dataWarehouseTables])

    const handleSelectGoal = (goalId: string | null): void => {
        if (!goalId) {
            return
        }

        // Handle "Define new core event" option
        if (goalId === DEFINE_NEW_CORE_EVENT) {
            router.actions.push(urls.coreEvents())
            return
        }

        const goal = (availableCoreEventsForExplore || []).find((g) => g.id === goalId)
        if (!goal) {
            return
        }

        // For DW goals, show schema_map configuration modal
        if (goal.filter.kind === NodeKind.DataWarehouseNode) {
            setSchemaMapForm({
                goal,
                schemaMap: { ...DEFAULT_SCHEMA_MAP },
                isSaving: false,
            })
        } else {
            // For events/actions, apply directly
            setDraftConversionGoal({
                ...goal.filter,
                conversion_goal_id: goal.id,
                conversion_goal_name: goal.name,
                schema_map: { ...DEFAULT_SCHEMA_MAP },
            })
        }
    }

    const handleConfirmSchemaMap = (): void => {
        if (!schemaMapForm) {
            return
        }

        const { goal, schemaMap, isSaving } = schemaMapForm

        if (isSaving) {
            // Save to marketing settings (create goal mapping)
            addGoalMapping(goal.id, {
                utm_campaign_name: schemaMap.utm_campaign_name,
                utm_source_name: schemaMap.utm_source_name,
            })
            // Clear the exploration since it's now saved
            clearConversionGoal()
        } else {
            // Just explore temporarily
            const dwFilter = goal.filter as DataWarehouseNode
            setDraftConversionGoal({
                ...goal.filter,
                conversion_goal_id: goal.id,
                conversion_goal_name: goal.name,
                schema_map: {
                    ...schemaMap,
                    timestamp_field: dwFilter.timestamp_field,
                    distinct_id_field: dwFilter.distinct_id_field,
                },
            })
        }
        setSchemaMapForm(null)
    }

    const handleSaveCurrentGoal = (): void => {
        if (!draftConversionGoal) {
            return
        }

        // Find the core event for this draft goal
        const goal = (availableCoreEventsForExplore || []).find((g) => g.id === draftConversionGoal.conversion_goal_id)

        if (goal?.filter.kind === NodeKind.DataWarehouseNode) {
            // For DW goals, show UTM mapping modal
            setSchemaMapForm({
                goal,
                schemaMap: {
                    utm_campaign_name: draftConversionGoal.schema_map?.utm_campaign_name || 'utm_campaign',
                    utm_source_name: draftConversionGoal.schema_map?.utm_source_name || 'utm_source',
                    timestamp_field: undefined,
                    distinct_id_field: undefined,
                },
                isSaving: true,
            })
        } else if (goal) {
            // For events/actions, save directly
            addGoalMapping(goal.id)
            clearConversionGoal()
        }
    }

    const coreEventOptions = (availableCoreEventsForExplore || []).map((goal) => ({
        value: goal.id,
        label: goal.name,
        labelInMenu: (
            <div className="flex flex-col">
                <span className="font-medium">{goal.name}</span>
                <span className="text-xs text-muted">
                    {getGoalTypeLabel(goal)}: {getGoalFilterSummary(goal)}
                </span>
            </div>
        ),
    }))

    const dropdownOptions = [
        ...coreEventOptions,
        {
            value: DEFINE_NEW_CORE_EVENT,
            label: 'Define new core event',
            labelInMenu: (
                <div className="flex items-center gap-2 text-primary">
                    <IconPlusSmall className="w-4 h-4" />
                    <span>Define new core event</span>
                </div>
            ),
        },
    ]

    return (
        <>
            <div className="flex items-center gap-1">
                <LemonSelect
                    size="small"
                    placeholder="Explore a core event"
                    options={dropdownOptions}
                    onChange={handleSelectGoal}
                    value={draftConversionGoal?.conversion_goal_id || null}
                />
                {draftConversionGoal && (
                    <>
                        <LemonButton
                            icon={<IconBookmark />}
                            size="small"
                            onClick={handleSaveCurrentGoal}
                            tooltip="Save as conversion goal"
                            type="tertiary"
                        />
                        <LemonButton
                            icon={<IconTrash />}
                            size="small"
                            onClick={clearConversionGoal}
                            tooltip="Clear exploration"
                            type="tertiary"
                        />
                    </>
                )}
            </div>

            <SchemaMapModal
                isOpen={!!schemaMapForm}
                onClose={() => setSchemaMapForm(null)}
                title={`Configure attribution mapping for "${schemaMapForm?.goal.name}"`}
                goalName={schemaMapForm?.goal.name || ''}
                schemaMap={schemaMapForm?.schemaMap || { utm_campaign_name: '', utm_source_name: '' }}
                onSchemaMapChange={(newSchemaMap) =>
                    setSchemaMapForm((prev) => (prev ? { ...prev, schemaMap: newSchemaMap } : null))
                }
                onConfirm={handleConfirmSchemaMap}
                confirmText={schemaMapForm?.isSaving ? 'Save as conversion goal' : 'Explore'}
                availableColumns={availableColumns}
            />
        </>
    )
}
