import { IconCheck, IconPencil, IconTrash, IconX } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { uuid } from 'lib/utils'
import { useState } from 'react'

import { ConversionGoalFilter } from '~/queries/schema/schema-general'

import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import { defaultConversionGoalFilter } from './constants'
import { ConversionGoalDropdown } from './ConversionGoalDropdown'

interface ConversionGoalFormState {
    filter: ConversionGoalFilter
    name: string
}

const createEmptyFormState = (): ConversionGoalFormState => ({
    filter: defaultConversionGoalFilter,
    name: '',
})

export function ConversionGoalsConfiguration(): JSX.Element {
    const { conversion_goals } = useValues(marketingAnalyticsSettingsLogic)
    const { addOrUpdateConversionGoal, removeConversionGoal } = useActions(marketingAnalyticsSettingsLogic)
    const [formState, setFormState] = useState<ConversionGoalFormState>(createEmptyFormState())
    const [editingGoalId, setEditingGoalId] = useState<string | null>(null)
    const [editingGoal, setEditingGoal] = useState<ConversionGoalFilter | null>(null)

    const handleAddConversionGoal = (): void => {
        const newGoal: ConversionGoalFilter = {
            ...formState.filter,
            conversion_goal_id: formState.filter.conversion_goal_id || uuid(),
            conversion_goal_name: formState.name.trim(),
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

    const isFormValid = formState.name.trim() !== '' && formState.filter.name

    return (
        <div className="space-y-6">
            <div>
                <h3 className="mb-2">Conversion Goals</h3>
                <p className="mb-4">
                    Define conversion goals by selecting events or data warehouse tables. These goals can be used to
                    track and analyze user conversions in your marketing analytics.
                </p>
            </div>

            {/* Add New Conversion Goal Form */}
            <div className="border rounded p-4 space-y-4">
                <h4 className="font-medium">Add New Conversion Goal</h4>

                <div className="space-y-3">
                    <div>
                        <label className="block text-sm font-medium mb-1">Conversion Goal Name</label>
                        <LemonInput
                            value={formState.name}
                            onChange={(value) => setFormState((prev) => ({ ...prev, name: value }))}
                            placeholder="e.g., Purchase, Sign Up, Download"
                        />
                    </div>

                    <div>
                        <label className="block text-sm font-medium mb-1">Select Event or Data Warehouse Table</label>
                        <ConversionGoalDropdown
                            value={formState.filter}
                            onChange={(filter: ConversionGoalFilter, uuid?: string) =>
                                setFormState((prev) => ({
                                    ...prev,
                                    filter: {
                                        ...filter,
                                        conversion_goal_id: uuid || filter.conversion_goal_id,
                                    },
                                }))
                            }
                        />
                    </div>

                    <div className="flex gap-2">
                        <LemonButton type="primary" onClick={handleAddConversionGoal} disabled={!isFormValid}>
                            Add Conversion Goal
                        </LemonButton>

                        <LemonButton onClick={() => setFormState(createEmptyFormState())}>Clear</LemonButton>
                    </div>
                </div>
            </div>

            {/* Existing Conversion Goals Table */}
            <div>
                <h4 className="font-medium mb-3">Configured Conversion Goals ({conversion_goals.length})</h4>

                <LemonTable
                    rowKey={(item) => item.conversion_goal_id}
                    dataSource={conversion_goals}
                    columns={[
                        {
                            key: 'name',
                            title: 'Goal Name',
                            render: (_, goal: ConversionGoalFilter) => {
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
                                return goal.conversion_goal_name
                            },
                        },
                        {
                            key: 'type',
                            title: 'Type',
                            render: (_, goal: ConversionGoalFilter) => goal.type,
                        },
                        {
                            key: 'event',
                            title: 'Event/Table',
                            render: (_, goal: ConversionGoalFilter) => {
                                if (editingGoalId === goal.conversion_goal_id && editingGoal) {
                                    return (
                                        <ConversionGoalDropdown
                                            value={editingGoal}
                                            onChange={(filter: ConversionGoalFilter) => setEditingGoal(filter)}
                                        />
                                    )
                                }
                                return goal.name || goal.id
                            },
                        },
                        {
                            key: 'schema',
                            title: 'Schema Mapping',
                            render: (_, goal: ConversionGoalFilter) => (
                                <div className="text-xs text-muted">
                                    <div>Campaign: {goal.schema.utm_campaign_name}</div>
                                    <div>Source: {goal.schema.utm_source_name}</div>
                                </div>
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
        </div>
    )
}
