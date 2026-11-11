import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef, useState } from 'react'

import { IconCheck, IconPencil, IconPlusSmall, IconTrash, IconWarning, IconX } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { QUERY_TYPES_METADATA } from 'scenes/saved-insights/insightTypesMetadata'
import { teamLogic } from 'scenes/teamLogic'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { ConversionGoalFilter, NodeKind } from '~/queries/schema/schema-general'

import { conversionGoalFormLogic } from 'products/marketing_analytics/frontend/setup/conversionGoalFormLogic'

import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import { ConversionGoalDropdown } from '../common/ConversionGoalDropdown'
import {
    MarketingAnalyticsValidationWarningBanner,
    validateConversionGoals,
} from '../MarketingAnalyticsValidationWarningBanner'
import {
    conversionGoalDescription,
    conversionGoalNamePlaceholder,
    getConfiguredConversionGoalsLabel,
} from './constants'
import { revenueDisabledReason, withValidFlags } from './conversionGoalFlags'

function CountsAsToggles({
    goal,
    onChange,
    disabledReason,
}: {
    goal: ConversionGoalFilter
    onChange: (goal: ConversionGoalFilter) => void
    disabledReason?: string | null
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <LemonCheckbox
                size="small"
                label="Revenue"
                checked={!!goal.counts_as_revenue}
                onChange={(counts_as_revenue) => onChange({ ...goal, counts_as_revenue })}
                disabledReason={disabledReason || revenueDisabledReason(goal)}
            />
            <LemonCheckbox
                size="small"
                label="Customer"
                checked={!!goal.counts_as_customer}
                onChange={(counts_as_customer) => onChange({ ...goal, counts_as_customer })}
                disabledReason={disabledReason}
            />
        </div>
    )
}

export function ConversionGoalsConfiguration({
    hideTitle = false,
    hideDescription = false,
}: {
    hideTitle?: boolean
    hideDescription?: boolean
}): JSX.Element {
    const { conversion_goals } = useValues(marketingAnalyticsSettingsLogic)
    const { addOrUpdateConversionGoal, removeConversionGoal } = useActions(marketingAnalyticsSettingsLogic)
    const { currentTeamId } = useValues(teamLogic)
    const formLogic = conversionGoalFormLogic({ projectId: currentTeamId ?? -1 })
    const {
        filter,
        name,
        recommendation,
        editingGoalId: reviewingGoalId,
        duplicateGoal,
        formFocusRequested,
        isFormValid,
        isSaving,
        currentTeamLoading,
        saveError,
    } = useValues(formLogic)
    const { setName, setFilter, saveGoal, clearDraft, reviewGoal, formFocused } = useActions(formLogic)
    const formRef = useRef<HTMLDivElement>(null)
    const nameInputRef = useRef<HTMLInputElement>(null)
    useEffect(() => {
        if (formFocusRequested) {
            formRef.current?.scrollIntoView({ block: 'nearest' })
            nameInputRef.current?.focus({ preventScroll: true })
            formFocused()
        }
    }, [formFocusRequested, formFocused])
    const [editingGoalId, setEditingGoalId] = useState<string | null>(null)
    const [editingGoal, setEditingGoal] = useState<ConversionGoalFilter | null>(null)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const validationWarnings = useMemo(() => validateConversionGoals(conversion_goals), [conversion_goals])

    const handleStartEdit = (goal: ConversionGoalFilter): void => {
        setEditingGoalId(goal.conversion_goal_id)
        setEditingGoal({ ...goal })
    }

    const handleSaveEdit = (): void => {
        if (editingGoal) {
            addOrUpdateConversionGoal(withValidFlags(editingGoal))
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

    const formDisabledReason =
        restrictedReason || (isSaving ? 'Wait for this conversion goal to finish saving.' : undefined)

    return (
        <SceneSection
            title={!hideTitle ? 'Conversion goals' : undefined}
            description={!hideDescription ? conversionGoalDescription : undefined}
        >
            {validationWarnings.length > 0 && (
                <MarketingAnalyticsValidationWarningBanner warnings={validationWarnings} />
            )}

            {/* Add New Conversion Goal Form */}
            <div ref={formRef} className="border rounded p-4 space-y-4" data-attr="marketing-conversion-goal-form">
                <h4 className="font-medium">
                    {reviewingGoalId ? 'Review conversion goal' : 'Add new conversion goal'}
                </h4>

                {!!recommendation?.questions.length && (
                    <LemonBanner type="info">
                        Review these questions before saving the goal:
                        <ul className="pl-5 mb-0 mt-2 space-y-1">
                            {recommendation.questions.map((question, index) => (
                                <li key={index}>{question}</li>
                            ))}
                        </ul>
                    </LemonBanner>
                )}
                {duplicateGoal && (
                    <LemonBanner
                        type="info"
                        action={{
                            children: 'Review goal',
                            onClick: () => reviewGoal(duplicateGoal.conversion_goal_id),
                            disabledReason:
                                formDisabledReason ||
                                (currentTeamLoading ? 'Wait for the project settings to finish saving.' : undefined),
                        }}
                    >
                        <span>{`Already configured as "${duplicateGoal.conversion_goal_name}". Review the existing goal.`}</span>
                    </LemonBanner>
                )}
                {saveError && <LemonBanner type="error">{saveError}</LemonBanner>}
                <div className="space-y-3">
                    <div>
                        <LemonInput
                            inputRef={nameInputRef}
                            value={name}
                            onChange={setName}
                            placeholder={conversionGoalNamePlaceholder}
                            disabledReason={formDisabledReason}
                        />
                    </div>

                    <div>
                        <ConversionGoalDropdown
                            value={filter}
                            typeKey="conversion-goal"
                            onChange={setFilter}
                            disabledReason={formDisabledReason}
                        />
                    </div>

                    <CountsAsToggles goal={filter} onChange={setFilter} disabledReason={formDisabledReason} />

                    <div className="flex gap-2">
                        <LemonButton
                            type="primary"
                            onClick={saveGoal}
                            loading={isSaving}
                            disabled={!isFormValid || currentTeamLoading}
                            size="small"
                            icon={reviewingGoalId ? <IconCheck /> : <IconPlusSmall />}
                            disabledReason={
                                formDisabledReason ||
                                (duplicateGoal ? 'Review the existing goal instead of adding a duplicate.' : undefined)
                            }
                        >
                            {reviewingGoalId ? 'Save changes' : 'Add conversion goal'}
                        </LemonButton>

                        <LemonButton onClick={clearDraft} disabledReason={formDisabledReason}>
                            Clear
                        </LemonButton>
                    </div>
                </div>
            </div>

            {/* Existing Conversion Goals Table */}
            <div>
                <h3 className="font-bold mb-4">{getConfiguredConversionGoalsLabel(conversion_goals.length)}</h3>

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
                                            disabledReason={restrictedReason}
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
                            key: 'counts_as',
                            title: 'Counts as',
                            render: (_, goal: ConversionGoalFilter) => {
                                if (editingGoalId === goal.conversion_goal_id && editingGoal) {
                                    return (
                                        <CountsAsToggles
                                            goal={editingGoal}
                                            onChange={setEditingGoal}
                                            disabledReason={restrictedReason}
                                        />
                                    )
                                }
                                const flags = [
                                    goal.counts_as_revenue && 'Revenue',
                                    goal.counts_as_customer && 'Customer',
                                ].filter(Boolean)
                                return flags.length ? (
                                    <span className="text-xs">{flags.join(', ')}</span>
                                ) : (
                                    <span className="text-xs text-muted">Conversions only</span>
                                )
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
                                                disabledReason={restrictedReason}
                                            />
                                            <LemonButton
                                                icon={<IconX />}
                                                size="small"
                                                onClick={handleCancelEdit}
                                                tooltip="Cancel"
                                                disabledReason={restrictedReason}
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
                                            disabledReason={restrictedReason}
                                        />
                                        <LemonButton
                                            icon={<IconTrash />}
                                            size="small"
                                            status="danger"
                                            onClick={() => handleRemoveGoal(goal.conversion_goal_id)}
                                            tooltip="Remove conversion goal"
                                            disabledReason={restrictedReason}
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
