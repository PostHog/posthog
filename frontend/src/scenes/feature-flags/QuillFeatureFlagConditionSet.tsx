import { useActions, useValues } from 'kea'
import type { CSSProperties, ReactNode } from 'react'

import { IconPeople, IconPerson } from '@posthog/icons'
import {
    Badge,
    Button,
    Collapsible,
    CollapsibleContent,
    CollapsibleHeader,
    CollapsibleTrigger,
    Field,
    FieldLabel,
    NumberFieldGroup,
    NumberFieldInput,
    NumberFieldRoot,
    Select,
    SelectContent,
    SelectGroup,
    SelectGroupLabel,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Slider,
    Text,
    cn,
} from '@posthog/quill'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { clamp, humanFriendlyNumber } from 'lib/utils/numbers'

import { groupsModel } from '~/models/groupsModel'

import { CohortFlagTargetingNotice } from 'products/cohorts/frontend/realtime/CohortFlagTargetingNotice'
import { useRealtimeCohortsServing } from 'products/cohorts/frontend/realtime/useRealtimeCohortsServing'

import { resolveAggregationGroupTypeIndex } from './aggregation'
import { CONDITION_SET_LOGICAL_OPERATOR_TOOLTIP } from './constants'
import { summarizeProperties } from './FeatureFlagReleaseConditionsCollapsible'
import {
    FeatureFlagGroupTypeWithSortKey,
    featureFlagReleaseConditionsLogic,
    withResolvedFlagLabels,
} from './featureFlagReleaseConditionsLogic'
import { getPropertySelectErrorMessages } from './propertySelectErrorMessages'
import { QuillConditionSetBlastRadius } from './QuillConditionSetBlastRadius'
import { QuillConditionSetDescription } from './QuillConditionSetDescription'
import { QuillConditionSetMenu } from './QuillConditionSetMenu'

const PERSON = 'person' as const
type AggregationValue = number | typeof PERSON

export interface QuillFeatureFlagConditionSetProps {
    group: FeatureFlagGroupTypeWithSortKey
    index: number
    totalGroups: number
    /** Scopes each condition set's property filter state, so two editors on one page keep separate filters. */
    conditionSetsId: string
    sortable?: {
        setNodeRef: (element: HTMLElement | null) => void
        style: CSSProperties
        isDragging: boolean
        dragHandle: ReactNode
    }
}

export function QuillFeatureFlagConditionSet({
    group,
    index,
    totalGroups,
    conditionSetsId,
    sortable,
}: QuillFeatureFlagConditionSetProps): JSX.Element {
    const {
        affectedCounts,
        aggregationTargetName,
        getDistinctIdName,
        getFlagKey,
        taxonomicGroupTypesForCondition,
        groupTypes,
        filtersTaxonomicOptions,
        filters: releaseFilters,
        propertySelectErrors,
        openConditions,
        isAnyItemDragging,
    } = useValues(featureFlagReleaseConditionsLogic)
    const {
        updateConditionSet,
        setConditionAggregation,
        setOpenConditions,
        duplicateConditionSet,
        removeConditionSet,
        moveConditionSetUp,
        moveConditionSetDown,
    } = useActions(featureFlagReleaseConditionsLogic)
    const { aggregationLabel } = useValues(groupsModel)
    const realtimeCohortFlagTargeting = useRealtimeCohortsServing()

    const conditionKey = `condition-${group.sort_key}`
    const isOpen = openConditions.includes(conditionKey)
    const rollout = group.rollout_percentage ?? 100
    const resolvedTargetName = aggregationTargetName(group.aggregation_group_type_index)
    const resolvedGroupTypeIndex = resolveAggregationGroupTypeIndex(
        group.aggregation_group_type_index,
        releaseFilters.aggregation_group_type_index
    )
    const resolvedSingularTargetName = aggregationLabel(resolvedGroupTypeIndex, true).singular

    const summary =
        group.description ||
        summarizeProperties(group.properties || [], resolvedTargetName, getDistinctIdName, getFlagKey)
    const affectedCount = affectedCounts[group.sort_key]
    const actualCount =
        affectedCount !== undefined && affectedCount >= 0
            ? Math.floor((affectedCount * clamp(rollout, 0, 100)) / 100)
            : null
    const countSummary = actualCount !== null ? `${humanFriendlyNumber(actualCount)} ${resolvedTargetName}` : null

    const aggregationItems = [
        { value: PERSON as AggregationValue, label: 'Users' },
        ...Array.from(groupTypes.values()).map((groupType) => ({
            value: groupType.group_type_index as AggregationValue,
            label:
                groupType.name_plural ||
                groupType.group_type.charAt(0).toUpperCase() + groupType.group_type.slice(1) + 's',
        })),
    ]
    const aggregationValue: AggregationValue =
        group.aggregation_group_type_index !== undefined
            ? (group.aggregation_group_type_index ?? PERSON)
            : (releaseFilters.aggregation_group_type_index ?? PERSON)

    function handleOpenChange(open: boolean): void {
        // A condition set that changes height mid-drag throws off the drop targets.
        if (isAnyItemDragging) {
            return
        }

        setOpenConditions(
            open ? [...openConditions, conditionKey] : openConditions.filter((key) => key !== conditionKey)
        )
    }

    function handleRolloutInput(value: number | null): void {
        const rounded = Math.round((value ?? 0) * 100) / 100
        updateConditionSet(index, Math.min(100, Math.max(0, rounded)))
    }

    return (
        <div
            ref={sortable?.setNodeRef}
            // dnd-kit moves the dragged row with an inline transform on every pointer move
            // oxlint-disable-next-line react/forbid-dom-props
            style={sortable?.style}
            className={cn('flex items-start gap-2', sortable?.isDragging && 'relative z-10 opacity-80')}
        >
            <Collapsible
                open={isOpen}
                onOpenChange={handleOpenChange}
                className={cn(
                    'min-w-0 flex-1 rounded-md border border-border bg-background p-2',
                    sortable?.isDragging && 'shadow-md'
                )}
            >
                <CollapsibleHeader className="flex-wrap">
                    <CollapsibleTrigger iconOnly>{`Toggle condition ${index + 1} details`}</CollapsibleTrigger>
                    <Badge>{index + 1}</Badge>
                    <Text size="xs" render={<span className="min-w-0 flex-1 break-all" />}>
                        {summary}
                    </Text>
                    <span className="ms-auto flex items-center gap-2">
                        <Text size="xs" variant="muted" render={<span className="tabular-nums" />}>
                            {`(${rollout}%${group.variant ? ` · ${group.variant}` : ''}${
                                countSummary !== null ? ` · ${countSummary}` : ''
                            })`}
                        </Text>
                        <QuillConditionSetMenu
                            canRemove={totalGroups > 1}
                            onDuplicate={() => duplicateConditionSet(index)}
                            onRemove={() => removeConditionSet(index)}
                        />
                    </span>
                </CollapsibleHeader>
                <CollapsibleContent className="flex flex-col gap-4 pt-2">
                    <QuillConditionSetDescription
                        description={group.description || ''}
                        dataAttr={`condition-set-${index}-description`}
                        onSave={(value) => updateConditionSet(index, undefined, undefined, undefined, value)}
                    />

                    {groupTypes.size > 0 && (
                        <Field className="w-fit">
                            <FieldLabel>Target by</FieldLabel>
                            <Select<AggregationValue>
                                items={aggregationItems}
                                value={aggregationValue}
                                onValueChange={(value: AggregationValue | null) => {
                                    if (value !== null) {
                                        setConditionAggregation(index, value === PERSON ? null : value)
                                    }
                                }}
                            >
                                <SelectTrigger
                                    className="min-w-40"
                                    aria-label="Target by"
                                    data-attr={`condition-set-${index}-aggregation`}
                                >
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectGroup>
                                        <SelectItem value={PERSON}>
                                            <IconPerson />
                                            Users
                                        </SelectItem>
                                    </SelectGroup>
                                    <SelectGroup>
                                        <SelectGroupLabel>Group types</SelectGroupLabel>
                                        {aggregationItems.slice(1).map((item) => (
                                            <SelectItem key={item.value} value={item.value}>
                                                <IconPeople />
                                                {item.label}
                                            </SelectItem>
                                        ))}
                                    </SelectGroup>
                                </SelectContent>
                            </Select>
                        </Field>
                    )}

                    <div className="flex flex-col gap-2">
                        <Text size="xs" weight="medium" render={<span />}>
                            Match filters
                        </Text>
                        <PropertyFilters
                            orFiltering={true}
                            pageKey={`feature-flag-workflow-${conditionSetsId}-${group.sort_key}`}
                            propertyFilters={withResolvedFlagLabels(group?.properties, getFlagKey)}
                            logicalRowDivider
                            logicalRowDividerTooltip={CONDITION_SET_LOGICAL_OPERATOR_TOOLTIP}
                            addText="Add filter"
                            onChange={(properties) => {
                                updateConditionSet(index, undefined, properties)
                            }}
                            taxonomicGroupTypes={taxonomicGroupTypesForCondition(group.aggregation_group_type_index)}
                            taxonomicFilterOptionsFromProp={filtersTaxonomicOptions}
                            hasRowOperator={false}
                            sendAllKeyUpdates
                            errorMessages={getPropertySelectErrorMessages(propertySelectErrors, index)}
                            hideBehavioralCohorts={!realtimeCohortFlagTargeting}
                            showCohortFlagTargeting
                            allowNonCapturedPersonProperties
                        />
                        <CohortFlagTargetingNotice properties={group.properties ?? []} />
                    </div>

                    <div className="flex flex-col gap-2">
                        <Text size="xs" weight="medium" render={<span />}>
                            Rollout percentage
                        </Text>
                        <div className="flex flex-wrap items-center gap-4">
                            <Slider
                                aria-label="Rollout percentage"
                                className="w-80 max-w-full"
                                value={rollout}
                                onValueChange={(value) =>
                                    updateConditionSet(index, Math.round(Array.isArray(value) ? value[0] : value))
                                }
                                min={0}
                                max={100}
                                step={1}
                            />
                            <div className="flex items-center gap-1">
                                <NumberFieldRoot
                                    className="w-20"
                                    value={rollout}
                                    onValueChange={handleRolloutInput}
                                    min={0}
                                    max={100}
                                    step={0.01}
                                    format={{ maximumFractionDigits: 2 }}
                                >
                                    <NumberFieldGroup>
                                        <NumberFieldInput
                                            aria-label="Rollout percentage"
                                            data-attr="rollout-percentage"
                                        />
                                    </NumberFieldGroup>
                                </NumberFieldRoot>
                                <Text size="xs" variant="muted" render={<span />}>
                                    %
                                </Text>
                            </div>
                        </div>
                        <QuillConditionSetBlastRadius
                            group={group}
                            resolvedGroupTypeIndex={resolvedGroupTypeIndex}
                            targetName={resolvedTargetName}
                            singularTargetName={resolvedSingularTargetName}
                        />
                    </div>
                </CollapsibleContent>
            </Collapsible>
            {totalGroups > 1 && (
                <div className="flex flex-col items-center gap-1">
                    {sortable?.dragHandle}
                    <div className="flex gap-1">
                        {index > 0 && (
                            <Button
                                size="icon-sm"
                                aria-label="Move up"
                                tooltip="Move up"
                                onClick={() => moveConditionSetUp(index)}
                            >
                                <IconArrowUp />
                            </Button>
                        )}
                        {index < totalGroups - 1 && (
                            <Button
                                size="icon-sm"
                                aria-label="Move down"
                                tooltip="Move down"
                                onClick={() => moveConditionSetDown(index)}
                            >
                                <IconArrowDown />
                            </Button>
                        )}
                    </div>
                </div>
            )}
        </div>
    )
}
