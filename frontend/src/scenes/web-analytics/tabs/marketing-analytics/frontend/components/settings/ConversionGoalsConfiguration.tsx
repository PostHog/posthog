import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconCheck, IconPencil, IconTrash, IconWarning, IconX } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { uuid } from 'lib/utils'
import { QUERY_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { ConversionGoalFilter, NodeKind } from '~/queries/schema/schema-general'

import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import {
    MarketingAnalyticsValidationWarningBanner,
    validateConversionGoals,
} from '../MarketingAnalyticsValidationWarningBanner'
import { ConversionGoalDropdown } from '../common/ConversionGoalDropdown'
import { defaultConversionGoalFilter } from './constants'

interface ConversionGoalFormState {
    filter: ConversionGoalFilter
    name: string
}

const createEmptyFormState = (): ConversionGoalFormState => ({
    filter: defaultConversionGoalFilter,
    name: '',
})

export function ConversionGoalsConfiguration({
    hideTitle = false,
    hideDescription = false,
}: {
    hideTitle?: boolean
    hideDescription?: boolean
}): JSX.Element {
    const { conversion_goals } = useValues(marketingAnalyticsSettingsLogic)
    const { addOrUpdateConversionGoal, removeConversionGoal } = useActions(marketingAnalyticsSettingsLogic)
    const [formState, setFormState] = useState<ConversionGoalFormState>(createEmptyFormState())
    const [editingGoalId, setEditingGoalId] = useState<string | null>(null)
    const [editingGoal, setEditingGoal] = useState<ConversionGoalFilter | null>(null)

    const validationWarnings = useMemo(() => validateConversionGoals(conversion_goals), [conversion_goals])

    const handleAddConversionGoal = (): void => {
        let conversionGoalName = formState.name.trim()
        if (conversionGoalName === '') {
            conversionGoalName = formState.filter.custom_name || formState.filter.name || 'No name'
        }
        const newGoal: ConversionGoalFilter = {
            ...formState.filter,
            conversion_goal_id: formState.filter.conversion_goal_id || uuid(),
            conversion_goal_name: conversionGoalName,
        }

        addOrUpdateConversionGoal(newGoal)
        setFormState(createEmptyFormState())
    }

    const handleStartEdit = (goal: ConversionGoalFilter): void => {
        setEditingGoalId(goal.conversion_goal_id)
        setEditingGoal({ ...goal })
    }

    const handleSaveEdit = (): void => {
        if (editingGoal) {
            addOrUpdateConversionGoal(editingGoal)
        }
        setEditingGoalId(null)
        setEditingGoal(null)
    }

    const handleCancelEdit = (): void => {
        setEditingGoalId(null)
        setEditingGoal(null)
    }

    const handleRemoveGoal = (goalId: string): void => {
        removeConversionGoal(goalId)
    }

    const isFormValid = defaultConversionGoalFilter.name !== formState.filter.name

    return (
        <SceneSection
            title={!hideTitle ? 'Conversion goals' : undefined}
            description={
                !hideDescription
                    ? 'Define conversion goals by selecting events or data warehouse tables. These goals can be used to track and analyze user conversions in your marketing analytics.'
                    : undefined
            }
        >
            {validationWarnings.length > 0 && (
                <MarketingAnalyticsValidationWarningBanner warnings={validationWarnings} />
            )}

            {/* Add New Conversion Goal Form */}
            <div className="border rounded p-4 space-y-4">
                <h4 className="font-medium">Add new conversion goal</h4>

                <div className="space-y-3">
                    <div>
                        <LemonInput
                            value={formState.name}
                            onChange={(value) => setFormState((prev) => ({ ...prev, name: value }))}
                            placeholder="Conversion goal name, e.g. purchase, sign up, download"
                        />
                    </div>

                    <div>
                        <ConversionGoalDropdown
                            value={formState.filter}
                            typeKey="conversion-goal"
                            onChange={(newFilter) =>
                                setFormState((prev) => ({
                                    ...prev,
                                    filter: {
                                        ...newFilter,
                                        conversion_goal_id: newFilter.conversion_goal_id || uuid(),
                                    },
                                }))
                            }
                        />
                    </div>

                    <div className="flex gap-2">
                        <LemonButton type="primary" onClick={handleAddConversionGoal} disabled={!isFormValid}>
                            Add conversion goal
                        </LemonButton>

                        <LemonButton onClick={() => setFormState(createEmptyFormState())}>Clear</LemonButton>
                    </div>
                </div>
            </div>

            {/* Existing Conversion Goals Table */}
            <div>
                <h3 className="font-bold mb-4">Configured conversion goals ({conversion_goals.length})</h3>

                <LemonTable
                    rowKey={(item) => item.conversion_goal_id}
                    dataSource={conversion_goals}
                    columns={[
                        {
                            key: 'name',
                            title: 'Goal name',
                            render: (_, goal: ConversionGoalFilter) => {
                                // Check if this goal is invalid (All Events)
                                const isInvalid =
                                    goal.kind === NodeKind.EventsNode &&
                                    ('event' in goal
                                        ? (goal as any).event === null || (goal as any).event === ''
                                        : false)

                                if (editingGoalId === goal.conversion_goal_id && editingGoal) {
                                    return (
                                        <LemonInput
                                            value={editingGoal.conversion_goal_name}
                                            onChange={(value) =>
                                                setEditingGoal((prev) =>
                                                    prev ? { ...prev, conversion_goal_name: value } : null
                                                )
                                            }
                                            size="small"
                                        />
                                    )
                                }
                                return (
                                    <div className={isInvalid ? 'flex items-center gap-1.5' : ''}>
                                        <span className={isInvalid ? 'text-warning' : ''}>
                                            {goal.conversion_goal_name}
                                        </span>
                                        {isInvalid && <IconWarning className="text-warning w-4 h-4 shrink-0" />}
                                    </div>
                                )
                            },
                        },
                        {
                            key: 'type',
                            title: 'Type',
                            render: (_, goal: ConversionGoalFilter) => QUERY_TYPES_METADATA[goal.kind]?.name,
                        },
                        {
                            key: 'event',
                            title: 'Event/Table',
                            render: (_, goal: ConversionGoalFilter) => {
                                if (editingGoalId === goal.conversion_goal_id && editingGoal) {
                                    return (
                                        <ConversionGoalDropdown
                                            value={editingGoal}
                                            typeKey="conversion-goal-edit"
                                            onChange={setEditingGoal}
                                        />
                                    )
                                }
                                return goal.custom_name || goal.name || 'No name'
                            },
                        },
                        {
                            key: 'schema',
                            title: 'Schema mapping',
                            render: (_, goal: ConversionGoalFilter) =>
                                goal.schema_map ? (
                                    <div className="text-xs text-muted">
                                        <div>Campaign: {goal.schema_map.utm_campaign_name}</div>
                                        <div>Source: {goal.schema_map.utm_source_name}</div>
                                        {goal.kind === 'DataWarehouseNode' && goal.schema_map.timestamp_field && (
                                            <div>Timestamp: {goal.schema_map.timestamp_field}</div>
                                        )}
                                        {goal.kind === 'DataWarehouseNode' && goal.schema_map.distinct_id_field && (
                                            <div>Distinct ID: {goal.schema_map.distinct_id_field}</div>
                                        )}
                                    </div>
                                ) : (
                                    <div>Not configured</div>
                                ),
                        },
                        {
                            key: 'actions',
                            title: 'Actions',
                            width: 100,
                            render: (_, goal: ConversionGoalFilter) => {
                                if (editingGoalId === goal.conversion_goal_id) {
                                    return (
                                        <div className="flex gap-1">
                                            <LemonButton
                                                icon={<IconCheck />}
                                                size="small"
                                                type="primary"
                                                onClick={handleSaveEdit}
                                                tooltip="Save changes"
                                            />
                                            <LemonButton
                                                icon={<IconX />}
                                                size="small"
                                                onClick={handleCancelEdit}
                                                tooltip="Cancel"
                                            />
                                        </div>
                                    )
                                }

                                return (
                                    <div className="flex gap-1">
                                        <LemonButton
                                            icon={<IconPencil />}
                                            size="small"
                                            onClick={() => handleStartEdit(goal)}
                                            tooltip="Edit conversion goal"
                                        />
                                        <LemonButton
                                            icon={<IconTrash />}
                                            size="small"
                                            status="danger"
                                            onClick={() => handleRemoveGoal(goal.conversion_goal_id)}
                                            tooltip="Remove conversion goal"
                                        />
                                    </div>
                                )
                            },
                        },
                    ]}
                    emptyState="No conversion goals configured yet. Add your first conversion goal above."
                />
            </div>
        </SceneSection>
    )
}
