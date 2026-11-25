import type { CellContext, ColumnDef } from '@tanstack/react-table'
import { createContext, useContext } from 'react'
import type { RefObject } from 'react'

import { IconCheck, IconPencil, IconPlus, IconTrash, IconWarning, IconX } from '@posthog/icons'
import {
    Button,
    DataTable,
    Field,
    Heading,
    Input,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    Text,
} from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { QUERY_TYPES_METADATA } from 'scenes/saved-insights/insightTypesMetadata'

import { ConversionGoalFilter } from '~/queries/schema/schema-general'

import type { ConversionRecommendationApi } from 'products/marketing_analytics/frontend/generated/api.schemas'

import { ConversionGoalDropdown } from '../common/ConversionGoalDropdown'
import { MarketingAnalyticsValidationWarningBanner } from '../MarketingAnalyticsValidationWarningBanner'
import type { validateConversionGoals } from '../MarketingAnalyticsValidationWarningBanner'
import {
    conversionGoalDescription,
    conversionGoalNamePlaceholder,
    getConfiguredConversionGoalsLabel,
} from './constants'
import { isInvalidConversionGoal } from './isInvalidConversionGoal'
import { QuillCountsAsToggles } from './QuillCountsAsToggles'

interface ConversionGoalRowEditing {
    editingGoalId: string | null
    editingGoal: ConversionGoalFilter | null
    onEditingGoalChange: React.Dispatch<React.SetStateAction<ConversionGoalFilter | null>>
    restrictedReason: string | null
    onStartEdit: (goal: ConversionGoalFilter) => void
    onSaveEdit: () => void
    onCancelEdit: () => void
    onRemoveGoal: (goalId: string) => void
}

// DataTable renders each cell function as a component, so the cells live at module scope and read the edit state
// from context. Recreating them on every render would remount the name input and drop focus on each keystroke.
const ConversionGoalRowEditingContext = createContext<ConversionGoalRowEditing | null>(null)

function useConversionGoalRowEditing(): ConversionGoalRowEditing {
    const rowEditing = useContext(ConversionGoalRowEditingContext)
    if (!rowEditing) {
        throw new Error('Conversion goal cells must render inside ConversionGoalRowEditingContext')
    }
    return rowEditing
}

function GoalNameCell({ row }: CellContext<ConversionGoalFilter, unknown>): JSX.Element {
    const { editingGoalId, editingGoal, onEditingGoalChange, restrictedReason } = useConversionGoalRowEditing()
    const goal = row.original

    if (editingGoalId === goal.conversion_goal_id && editingGoal) {
        return (
            <Input
                size="sm"
                aria-label="Goal name"
                value={editingGoal.conversion_goal_name}
                onChange={(event) => {
                    const value = event.target.value
                    onEditingGoalChange((prev) => (prev ? { ...prev, conversion_goal_name: value } : null))
                }}
                disabledReason={restrictedReason}
            />
        )
    }

    if (isInvalidConversionGoal(goal)) {
        return (
            <span className="flex items-center gap-1.5 text-warning-foreground">
                <span>{goal.conversion_goal_name}</span>
                <IconWarning className="size-4 shrink-0" />
            </span>
        )
    }

    return <span>{goal.conversion_goal_name}</span>
}

function GoalEventCell({ row }: CellContext<ConversionGoalFilter, unknown>): JSX.Element {
    const { editingGoalId, editingGoal, onEditingGoalChange } = useConversionGoalRowEditing()
    const goal = row.original

    if (editingGoalId === goal.conversion_goal_id && editingGoal) {
        return (
            <ConversionGoalDropdown value={editingGoal} typeKey="conversion-goal-edit" onChange={onEditingGoalChange} />
        )
    }

    return <>{goal.custom_name || goal.name || 'No name'}</>
}

function GoalCountsAsCell({ row }: CellContext<ConversionGoalFilter, unknown>): JSX.Element {
    const { editingGoalId, editingGoal, onEditingGoalChange, restrictedReason } = useConversionGoalRowEditing()
    const recommendationsEnabled = useFeatureFlag('MARKETING_ANALYTICS_RECOMMENDATIONS')
    const goal = row.original

    if (editingGoalId === goal.conversion_goal_id && editingGoal) {
        return (
            <QuillCountsAsToggles goal={editingGoal} onChange={onEditingGoalChange} disabledReason={restrictedReason} />
        )
    }

    const flags = [
        goal.counts_as_revenue && 'Revenue',
        goal.counts_as_customer && 'Customer',
        recommendationsEnabled && goal.use_in_recommendations && 'Recommendations',
    ].filter(Boolean)

    return flags.length ? (
        <Text size="xs" render={<span />}>
            {flags.join(', ')}
        </Text>
    ) : (
        <Text size="xs" variant="muted" render={<span />}>
            Conversions only
        </Text>
    )
}

function GoalSchemaCell({ row }: CellContext<ConversionGoalFilter, unknown>): JSX.Element {
    const goal = row.original

    if (!goal.schema_map) {
        return <span>Not configured</span>
    }

    return (
        <Text size="xs" variant="muted" render={<div className="flex flex-col" />}>
            <span>{`Campaign: ${goal.schema_map.utm_campaign_name}`}</span>
            <span>{`Source: ${goal.schema_map.utm_source_name}`}</span>
            {goal.kind === 'DataWarehouseNode' && goal.schema_map.timestamp_field && (
                <span>{`Timestamp: ${goal.schema_map.timestamp_field}`}</span>
            )}
            {goal.kind === 'DataWarehouseNode' && goal.schema_map.distinct_id_field && (
                <span>{`Distinct ID: ${goal.schema_map.distinct_id_field}`}</span>
            )}
        </Text>
    )
}

function GoalActionsCell({ row }: CellContext<ConversionGoalFilter, unknown>): JSX.Element {
    const { editingGoalId, restrictedReason, onStartEdit, onSaveEdit, onCancelEdit, onRemoveGoal } =
        useConversionGoalRowEditing()
    const goal = row.original

    if (editingGoalId === goal.conversion_goal_id) {
        return (
            <div className="flex justify-end gap-1">
                <Button
                    size="icon-sm"
                    variant="primary"
                    aria-label="Save changes"
                    tooltip="Save changes"
                    onClick={onSaveEdit}
                    disabledReason={restrictedReason}
                >
                    <IconCheck />
                </Button>
                <Button
                    size="icon-sm"
                    aria-label="Cancel"
                    tooltip="Cancel"
                    onClick={onCancelEdit}
                    disabledReason={restrictedReason}
                >
                    <IconX />
                </Button>
            </div>
        )
    }

    return (
        <div className="flex justify-end gap-1">
            <Button
                size="icon-sm"
                aria-label="Edit conversion goal"
                tooltip="Edit conversion goal"
                onClick={() => onStartEdit(goal)}
                disabledReason={restrictedReason}
            >
                <IconPencil />
            </Button>
            <Button
                size="icon-sm"
                variant="destructive-outline"
                aria-label="Remove conversion goal"
                tooltip="Remove conversion goal"
                onClick={() => onRemoveGoal(goal.conversion_goal_id)}
                disabledReason={restrictedReason}
            >
                <IconTrash />
            </Button>
        </div>
    )
}

const COLUMNS: ColumnDef<ConversionGoalFilter>[] = [
    { id: 'name', header: 'Goal name', meta: { expand: true }, cell: GoalNameCell },
    { id: 'type', header: 'Type', cell: ({ row }) => QUERY_TYPES_METADATA[row.original.kind]?.name },
    { id: 'event', header: 'Event/Table', cell: GoalEventCell },
    { id: 'counts_as', header: 'Counts as', cell: GoalCountsAsCell },
    { id: 'schema', header: 'Schema mapping', cell: GoalSchemaCell },
    { id: 'actions', header: 'Actions', meta: { align: 'right' }, cell: GoalActionsCell },
]

export function QuillConversionGoalsConfiguration({
    hideTitle,
    hideDescription,
    conversionGoals,
    validationWarnings,
    formRef,
    nameInputRef,
    reviewingGoalId,
    recommendation,
    duplicateGoal,
    saveError,
    name,
    onNameChange,
    filter,
    onFilterChange,
    isFormValid,
    isSaving,
    currentTeamLoading,
    formDisabledReason,
    reviewGoalDisabledReason,
    saveGoalDisabledReason,
    onSaveGoal,
    onClearDraft,
    onReviewGoal,
    editingGoalId,
    editingGoal,
    onEditingGoalChange,
    restrictedReason,
    onStartEdit,
    onSaveEdit,
    onCancelEdit,
    onRemoveGoal,
}: {
    hideTitle: boolean
    hideDescription: boolean
    conversionGoals: ConversionGoalFilter[]
    validationWarnings: ReturnType<typeof validateConversionGoals>
    formRef: RefObject<HTMLDivElement>
    nameInputRef: RefObject<HTMLInputElement>
    reviewingGoalId: string | null
    recommendation: ConversionRecommendationApi | null
    duplicateGoal: ConversionGoalFilter | null
    saveError: string | null
    name: string
    onNameChange: (name: string) => void
    filter: ConversionGoalFilter
    onFilterChange: (filter: ConversionGoalFilter) => void
    isFormValid: boolean
    isSaving: boolean
    currentTeamLoading: boolean
    formDisabledReason: string | null | undefined
    reviewGoalDisabledReason: string | null | undefined
    saveGoalDisabledReason: string | null | undefined
    onSaveGoal: () => void
    onClearDraft: () => void
    onReviewGoal: (goalId: string) => void
    editingGoalId: string | null
    editingGoal: ConversionGoalFilter | null
    onEditingGoalChange: React.Dispatch<React.SetStateAction<ConversionGoalFilter | null>>
    restrictedReason: string | null
    onStartEdit: (goal: ConversionGoalFilter) => void
    onSaveEdit: () => void
    onCancelEdit: () => void
    onRemoveGoal: (goalId: string) => void
}): JSX.Element {
    const rowEditing: ConversionGoalRowEditing = {
        editingGoalId,
        editingGoal,
        onEditingGoalChange,
        restrictedReason,
        onStartEdit,
        onSaveEdit,
        onCancelEdit,
        onRemoveGoal,
    }

    return (
        <section className="flex flex-col gap-4">
            {(!hideTitle || !hideDescription) && (
                <div className="flex flex-col gap-1">
                    {!hideTitle && (
                        <Heading size="sm" render={<h3 className="m-0" />}>
                            Conversion goals
                        </Heading>
                    )}
                    {!hideDescription && (
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            {conversionGoalDescription}
                        </Text>
                    )}
                </div>
            )}

            {validationWarnings.length > 0 && (
                <MarketingAnalyticsValidationWarningBanner warnings={validationWarnings} />
            )}

            <div
                ref={formRef}
                className="flex flex-col gap-3 rounded-lg border border-border p-4"
                data-attr="marketing-conversion-goal-form"
            >
                <Heading size="sm" render={<h4 className="m-0" />}>
                    {reviewingGoalId ? 'Review conversion goal' : 'Add new conversion goal'}
                </Heading>

                {!!recommendation?.questions.length && (
                    <Item tone="info" size="sm">
                        <ItemContent>
                            <ItemDescription>Review these questions before saving the goal:</ItemDescription>
                            <Text size="xs" render={<ul className="m-0 flex list-disc flex-col gap-1 ps-5" />}>
                                {recommendation.questions.map((question, index) => (
                                    <li key={index}>{question}</li>
                                ))}
                            </Text>
                        </ItemContent>
                    </Item>
                )}

                {duplicateGoal && (
                    <Item tone="info" size="sm">
                        <ItemContent>
                            <ItemDescription>{`Already configured as "${duplicateGoal.conversion_goal_name}". Review the existing goal.`}</ItemDescription>
                        </ItemContent>
                        <ItemActions>
                            <Button
                                variant="outline"
                                onClick={() => onReviewGoal(duplicateGoal.conversion_goal_id)}
                                disabledReason={reviewGoalDisabledReason}
                            >
                                Review goal
                            </Button>
                        </ItemActions>
                    </Item>
                )}

                {saveError && (
                    <Item tone="destructive" size="sm">
                        <ItemContent>
                            <ItemDescription>{saveError}</ItemDescription>
                        </ItemContent>
                    </Item>
                )}

                <Field>
                    <Input
                        ref={nameInputRef}
                        aria-label="Conversion goal name"
                        value={name}
                        onChange={(event) => onNameChange(event.target.value)}
                        placeholder={conversionGoalNamePlaceholder}
                        disabledReason={formDisabledReason}
                    />
                </Field>

                <ConversionGoalDropdown
                    value={filter}
                    typeKey="conversion-goal"
                    onChange={onFilterChange}
                    disabledReason={formDisabledReason}
                />

                <QuillCountsAsToggles goal={filter} onChange={onFilterChange} disabledReason={formDisabledReason} />

                <div className="flex flex-wrap gap-2">
                    <Button
                        variant="primary"
                        onClick={onSaveGoal}
                        loading={isSaving}
                        disabled={!isFormValid || currentTeamLoading}
                        disabledReason={saveGoalDisabledReason}
                    >
                        {reviewingGoalId ? <IconCheck /> : <IconPlus />}
                        {reviewingGoalId ? 'Save changes' : 'Add conversion goal'}
                    </Button>
                    <Button onClick={onClearDraft} disabledReason={formDisabledReason}>
                        Clear
                    </Button>
                </div>
            </div>

            <div className="flex flex-col gap-2">
                <Heading size="sm" render={<h3 className="m-0" />}>
                    {getConfiguredConversionGoalsLabel(conversionGoals.length)}
                </Heading>
                <ConversionGoalRowEditingContext.Provider value={rowEditing}>
                    <DataTable
                        columns={COLUMNS}
                        data={conversionGoals}
                        getRowId={(goal) => goal.conversion_goal_id}
                        fullWidth
                        empty="No conversion goals configured yet. Add your first conversion goal above."
                    />
                </ConversionGoalRowEditingContext.Provider>
            </div>
        </section>
    )
}
