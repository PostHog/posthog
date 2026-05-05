import {
    DndContext,
    DragEndEvent,
    DragOverlay,
    DragStartEvent,
    KeyboardSensor,
    PointerSensor,
    useSensor,
    useSensors,
    rectIntersection,
} from '@dnd-kit/core'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useActions, useValues } from 'kea'
import React, { useRef, useState } from 'react'
import { v4 as uuidv4 } from 'uuid'

import {
    IconBalance,
    IconCollapse,
    IconCopy,
    IconEllipsis,
    IconExpand,
    IconInfo,
    IconLaptop,
    IconPeople,
    IconPerson,
    IconPlus,
    IconTrash,
    IconCheckCircle,
} from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonLabel,
    LemonMenu,
    LemonSelect,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { allOperatorsToHumanName } from 'lib/components/DefinitionPopover/utils'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isPropertyFilterWithOperator } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType, TaxonomicFilterProps } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyNumber } from 'lib/utils'
import { clamp } from 'lib/utils'

import {
    AnyPropertyFilter,
    FeatureFlagBucketingIdentifier,
    FeatureFlagEvaluationRuntime,
    FeatureFlagFilters,
    FeatureFlagGroupType,
    GroupType,
    GroupTypeIndex,
    MultivariateFlagVariant,
    PropertyFilterType,
} from '~/types'

import { INTENT_METADATA } from 'products/feature_flags/frontend/featureFlagTemplateConstants'

import { FeatureFlagConditionDragHandle } from './FeatureFlagConditionDragHandle'
import { FeatureFlagConditionWarning } from './FeatureFlagConditionWarning'
import { FlagIntent, featureFlagIntentWarningLogic } from './featureFlagIntentWarningLogic'
import { FeatureFlagLogicProps } from './featureFlagLogic'
import {
    FeatureFlagReleaseConditionsLogicProps,
    FeatureFlagGroupTypeWithSortKey,
    featureFlagReleaseConditionsLogic,
} from './featureFlagReleaseConditionsLogic'

interface FeatureFlagReleaseConditionsCollapsibleProps extends FeatureFlagReleaseConditionsLogicProps {
    flagId?: FeatureFlagLogicProps['id']
    readOnly?: boolean
    variants?: MultivariateFlagVariant[]
    isDisabled?: boolean
    bucketingIdentifier?: FeatureFlagBucketingIdentifier | null
    onBucketingIdentifierChange?: (value: FeatureFlagBucketingIdentifier | null) => void
    evaluationRuntime?: FeatureFlagEvaluationRuntime
    /** When true, hides the "Match by" User/Group selector. Use when the aggregation type is inherited from the parent flag. */
    hideMatchOptions?: boolean
}

function summarizeProperties(properties: AnyPropertyFilter[], aggregationTargetName: string): string {
    if (!properties || properties.length === 0) {
        // Capitalize first letter of aggregation target name
        const capitalizedTarget = aggregationTargetName.charAt(0).toUpperCase() + aggregationTargetName.slice(1)
        return `All ${capitalizedTarget}`
    }

    const parts = properties.slice(0, 2).map((property) => {
        let key: string
        if (property.type === PropertyFilterType.Cohort) {
            key = 'Cohort'
        } else if (property.type === PropertyFilterType.Flag) {
            key = property.label || property.key || 'flag'
        } else {
            key = property.key || 'property'
        }
        const operator = isPropertyFilterWithOperator(property) ? allOperatorsToHumanName(property.operator) : 'is'
        const groupKeyNames: Record<string, string> =
            property.key === '$group_key' && property.type === PropertyFilterType.Group && 'group_key_names' in property
                ? ((property as any).group_key_names ?? {})
                : {}
        const hasGroupKeyNames = Object.keys(groupKeyNames).length > 0

        let value: string | number
        if (property.type === PropertyFilterType.Cohort) {
            value = property.cohort_name || `ID ${property.value}`
        } else if (Array.isArray(property.value)) {
            const displayValues = hasGroupKeyNames
                ? property.value.map((v) => groupKeyNames[String(v)] || String(v))
                : property.value.map(String)
            value = displayValues.slice(0, 2).join(', ') + (displayValues.length > 2 ? '...' : '')
        } else if (property.value === null || property.value === undefined) {
            value = ''
        } else {
            value = hasGroupKeyNames
                ? groupKeyNames[String(property.value)] || String(property.value)
                : String(property.value)
        }

        return `${key} ${operator} ${value}`
    })

    if (properties.length > 2) {
        parts.push(`+${properties.length - 2} more`)
    }

    return parts.join(' AND ')
}

interface ConditionHeaderProps {
    group: FeatureFlagGroupType
    index: number
    totalGroups: number
    affectedCount: number | undefined
    aggregationTargetName: string
    onDuplicate: () => void
    onRemove: () => void
}

function ConditionHeader({
    group,
    index,
    totalGroups,
    affectedCount,
    aggregationTargetName,
    onDuplicate,
    onRemove,
}: ConditionHeaderProps): JSX.Element {
    // Use description if available, otherwise summarize the filters
    const summary = group.description || summarizeProperties(group.properties || [], aggregationTargetName)
    const rollout = group.rollout_percentage ?? 100

    const actualCount =
        affectedCount !== undefined && affectedCount >= 0
            ? Math.floor((affectedCount * clamp(rollout, 0, 100)) / 100)
            : null

    const countSummary = actualCount !== null ? `${humanFriendlyNumber(actualCount)} ${aggregationTargetName}` : null

    return (
        <div className="flex items-center justify-between w-full gap-2">
            <div className="flex items-center gap-2 min-w-0">
                <span className="font-medium text-xs bg-bg-light rounded px-1.5 py-0.5 shrink-0">{index + 1}</span>
                <span className="text-sm break-all">{summary}</span>
            </div>
            <div className="flex items-center gap-2 shrink-0">
                <span className="text-sm text-muted mr-2">
                    ({rollout}%{group.variant && ` · ${group.variant}`}
                    {countSummary !== null && ` · ${countSummary}`})
                </span>
                <LemonMenu
                    items={[
                        {
                            label: 'Duplicate condition set',
                            icon: <IconCopy />,
                            onClick: onDuplicate,
                        },
                        ...(totalGroups > 1
                            ? [
                                  {
                                      label: 'Remove condition set',
                                      icon: <IconTrash />,
                                      onClick: onRemove,
                                      status: 'danger' as const,
                                  },
                              ]
                            : []),
                    ]}
                >
                    <LemonButton
                        icon={<IconEllipsis />}
                        size="xsmall"
                        noPadding
                        aria-label="Condition set actions"
                        onClick={(e) => e.stopPropagation()}
                    />
                </LemonMenu>
            </div>
        </div>
    )
}

function IntentIssuesSummary({
    issues,
    intent,
    expanded,
    onToggle,
}: {
    issues: string[]
    intent: FlagIntent | null
    expanded: boolean
    onToggle: () => void
}): JSX.Element | null {
    if (issues.length === 0 || !intent) {
        return null
    }

    const metadata = INTENT_METADATA[intent]
    const label = issues.length === 1 ? '1 issue detected' : `${issues.length} issues detected`

    return (
        <LemonBanner type="warning">
            <div>
                <div className="flex items-center justify-between cursor-pointer select-none" onClick={onToggle}>
                    <span className="text-sm font-medium">{label}</span>
                    <span className="text-xs text-secondary">{expanded ? 'Hide' : 'Show'}</span>
                </div>
                {expanded && (
                    <div className="mt-1.5">
                        <p className="text-xs text-secondary mb-1.5">{metadata.consequence}</p>
                        <ul className="list-disc pl-4 mb-0 space-y-0.5">
                            {issues.map((issue, i) => (
                                <li key={i} className="text-xs">
                                    {issue}
                                </li>
                            ))}
                        </ul>
                        <Link to={metadata.docUrl} target="_blank" className="text-xs mt-1.5 block">
                            Learn more
                        </Link>
                    </div>
                )}
            </div>
        </LemonBanner>
    )
}

function IntentWarningsBanner({ flagId }: { flagId: FeatureFlagLogicProps['id'] }): JSX.Element | null {
    const { intentIssues, flagIntent, issuesExpanded } = useValues(featureFlagIntentWarningLogic({ id: flagId }))
    const { toggleIssuesExpanded } = useActions(featureFlagIntentWarningLogic({ id: flagId }))
    return (
        <IntentIssuesSummary
            issues={intentIssues}
            intent={flagIntent}
            expanded={issuesExpanded}
            onToggle={toggleIssuesExpanded}
        />
    )
}

function UnreachableConditionBanner({
    flagId,
    groupIndex,
}: {
    flagId: FeatureFlagLogicProps['id']
    groupIndex: number
}): JSX.Element | null {
    const { unreachableGroups } = useValues(featureFlagIntentWarningLogic({ id: flagId }))
    if (!unreachableGroups.has(groupIndex)) {
        return null
    }
    return (
        <LemonBanner type="warning" className="mb-1">
            <strong>Unreachable condition</strong> — A previous condition matches all users at 100% rollout, so this
            condition will never be evaluated.
        </LemonBanner>
    )
}

interface ConditionProps {
    group: FeatureFlagGroupTypeWithSortKey
    index: number
    totalGroups: number
    affectedCounts: Record<string, number | undefined>
    totalCounts: Record<string, number | undefined>
    aggregationTargetName: (conditionGroupTypeIndex?: number | null) => string
    taxonomicGroupTypesForCondition: (conditionGroupTypeIndex: number | null | undefined) => TaxonomicFilterGroupType[]
    groupTypes: Map<GroupTypeIndex, GroupType>
    setConditionAggregation: (index: number, groupTypeIndex: number | null) => void
    isMixedTargetingEnabled: boolean
    mixedGroupTypeIndex: number
    onMoveUp: () => void
    onMoveDown: () => void
    onDuplicate: () => void
    onRemove: () => void
    updateConditionSet: (
        index: number,
        rollout?: number,
        properties?: AnyPropertyFilter[],
        variant?: string | null,
        description?: string
    ) => void
    filtersTaxonomicOptions: TaxonomicFilterProps['optionsFromProp']
    releaseFilters: FeatureFlagFilters
    variants?: MultivariateFlagVariant[]
    openConditions: string[]
    handleOpenConditionsChange: (newKeys: string[]) => void
    flagId?: FeatureFlagLogicProps['id']
    id: string
    isAnyItemDragging: boolean
}

const DraggableCondition = (props: ConditionProps): JSX.Element => {
    const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({
        id: props.group.sort_key!, // sort_key is guaranteed by ensureSortKeys() in the logic
    })

    return (
        <ConditionContent
            {...props}
            attributes={attributes}
            listeners={listeners}
            setNodeRef={setNodeRef}
            setActivatorNodeRef={setActivatorNodeRef}
            transform={transform}
            transition={transition}
            isDragging={isDragging}
            isDragDropEnabled={true}
        />
    )
}

const StaticCondition = (props: ConditionProps): JSX.Element => {
    return (
        <ConditionContent
            {...props}
            attributes={{}}
            listeners={undefined}
            setNodeRef={() => {}}
            setActivatorNodeRef={() => {}}
            transform={null}
            transition={undefined}
            isDragging={false}
            isDragDropEnabled={false}
        />
    )
}

const ConditionContent = ({
    group,
    index,
    totalGroups,
    affectedCounts,
    totalCounts,
    aggregationTargetName,
    taxonomicGroupTypesForCondition,
    groupTypes,
    setConditionAggregation,
    isMixedTargetingEnabled,
    mixedGroupTypeIndex,
    onMoveUp,
    onMoveDown,
    onDuplicate,
    onRemove,
    updateConditionSet,
    filtersTaxonomicOptions,
    releaseFilters,
    variants,
    openConditions,
    handleOpenConditionsChange,
    flagId,
    id,
    isAnyItemDragging,
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
    isDragDropEnabled,
}: ConditionProps & {
    attributes: any
    listeners: any
    setNodeRef: any
    setActivatorNodeRef: any
    transform: any
    transition: any
    isDragging: boolean
    isDragDropEnabled: boolean
}): JSX.Element => {
    const [originalWidth, setOriginalWidth] = useState<number | undefined>(undefined)
    const realtimeCohortFlagTargeting = useFeatureFlag('REALTIME_COHORT_FLAG_TARGETING')

    // Combined ref callback
    const combinedRef = (element: HTMLDivElement | null): void => {
        setNodeRef(element)

        // Capture original width when element is first mounted
        if (element && !originalWidth) {
            setOriginalWidth(element.offsetWidth)
        }
    }

    const style = {
        transform: CSS.Transform.toString(transform),
        transition: isDragging ? undefined : transition,
        opacity: isDragging ? 0.8 : 1,
        zIndex: isDragging ? 1000 : 'auto',
        // Maintain original width during drag operations
        ...(isDragging && originalWidth && { width: originalWidth }),
        // Add shadow and background for better visual separation
        ...(isDragging && {
            boxShadow: '0 8px 25px rgba(0, 0, 0, 0.15)',
            backgroundColor: 'var(--bg-light)',
        }),
    }

    const toggleCondition = (): void => {
        // Prevent collapse/expand during ANY drag operation to maintain consistent heights
        if (isAnyItemDragging) {
            return
        }

        const conditionKey = `condition-${group.sort_key!}`
        const isOpen = openConditions.includes(conditionKey)
        const newOpenConditions = isOpen
            ? openConditions.filter((key) => key !== conditionKey)
            : [...openConditions, conditionKey]
        handleOpenConditionsChange(newOpenConditions)
    }

    const resolvedTargetName = aggregationTargetName(group.aggregation_group_type_index)

    return (
        <div
            ref={combinedRef}
            style={style}
            className={isDragging ? 'border-2 border-dashed border-border-light bg-bg-3000 rounded' : ''}
        >
            {flagId && <UnreachableConditionBanner flagId={flagId} groupIndex={index} />}
            <div className="flex items-start gap-3">
                <div className="flex-1">
                    <div className="border rounded bg-bg-light">
                        <div
                            className="flex items-center justify-between w-full p-3 cursor-pointer hover:bg-bg-dark transition-colors"
                            role="button"
                            tabIndex={0}
                            aria-expanded={openConditions.includes(`condition-${group.sort_key!}`)}
                            aria-label={`Toggle condition ${index + 1} details`}
                            onClick={() => {
                                // Prevent collapse/expand during ANY drag operation to maintain consistent heights
                                if (isAnyItemDragging) {
                                    return
                                }

                                toggleCondition()
                            }}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter' || e.key === ' ') {
                                    e.preventDefault()
                                    // Prevent collapse/expand during ANY drag operation to maintain consistent heights
                                    if (isAnyItemDragging) {
                                        return
                                    }

                                    toggleCondition()
                                }
                            }}
                        >
                            <ConditionHeader
                                group={group}
                                index={index}
                                totalGroups={totalGroups}
                                affectedCount={group.sort_key ? affectedCounts[group.sort_key] : undefined}
                                aggregationTargetName={aggregationTargetName(group.aggregation_group_type_index)}
                                onDuplicate={onDuplicate}
                                onRemove={onRemove}
                            />
                            <span className="ml-2">
                                {openConditions.includes(`condition-${group.sort_key!}`) ? (
                                    <IconCollapse className="w-4 h-4" />
                                ) : (
                                    <IconExpand className="w-4 h-4" />
                                )}
                            </span>
                        </div>
                        {openConditions.includes(`condition-${group.sort_key!}`) && (
                            <div className="p-3 pt-0 border-t">
                                <div className="flex flex-col gap-3 pt-2">
                                    <div className="max-w-md">
                                        <EditableField
                                            multiline
                                            name="description"
                                            value={group.description || ''}
                                            placeholder="Description (optional)"
                                            onSave={(value) =>
                                                updateConditionSet(index, undefined, undefined, undefined, value)
                                            }
                                            saveOnBlur={true}
                                            maxLength={600}
                                            data-attr={`condition-set-${index}-description`}
                                            compactButtons
                                        />
                                    </div>

                                    {isMixedTargetingEnabled && groupTypes.size > 0 && (
                                        <div>
                                            <LemonLabel className="mb-1">Targeting criteria</LemonLabel>
                                            <LemonSelect
                                                size="small"
                                                data-attr={`condition-set-${index}-aggregation`}
                                                value={group.aggregation_group_type_index != null ? 'group' : 'person'}
                                                onChange={(value) => {
                                                    setConditionAggregation(
                                                        index,
                                                        value === 'person' ? null : mixedGroupTypeIndex
                                                    )
                                                }}
                                                options={(() => {
                                                    const gt = groupTypes.get(mixedGroupTypeIndex as GroupTypeIndex)
                                                    const groupLabel = gt
                                                        ? gt.name_plural ||
                                                          gt.group_type.charAt(0).toUpperCase() +
                                                              gt.group_type.slice(1) +
                                                              's'
                                                        : 'Groups'
                                                    return [
                                                        { value: 'person' as const, label: 'Users' },
                                                        {
                                                            value: 'group' as const,
                                                            label: groupLabel,
                                                        },
                                                    ]
                                                })()}
                                            />
                                        </div>
                                    )}

                                    <div>
                                        <LemonLabel className="mb-1">Match filters</LemonLabel>
                                        <PropertyFilters
                                            orFiltering={true}
                                            pageKey={`feature-flag-workflow-${id}-${group.sort_key!}`}
                                            propertyFilters={group?.properties}
                                            logicalRowDivider
                                            addText="Add filter"
                                            onChange={(properties) => {
                                                updateConditionSet(index, undefined, properties)
                                            }}
                                            taxonomicGroupTypes={taxonomicGroupTypesForCondition(
                                                group.aggregation_group_type_index ??
                                                    releaseFilters.aggregation_group_type_index
                                            )}
                                            taxonomicFilterOptionsFromProp={filtersTaxonomicOptions}
                                            hasRowOperator={false}
                                            exactMatchFeatureFlagCohortOperators={true}
                                            hideBehavioralCohorts={!realtimeCohortFlagTargeting}
                                        />
                                    </div>

                                    <div>
                                        <LemonLabel className="mb-1">Rollout percentage</LemonLabel>
                                        <div className="flex items-start gap-6">
                                            <LemonSlider
                                                value={group.rollout_percentage ?? 100}
                                                onChange={(value) => updateConditionSet(index, Math.round(value))}
                                                min={0}
                                                max={100}
                                                step={1}
                                                className="w-80"
                                                ticks={[
                                                    { value: 0, label: '0%' },
                                                    { value: 10, label: '10%' },
                                                    { value: 25, label: '25%' },
                                                    { value: 50, label: '50%' },
                                                    { value: 75, label: '75%' },
                                                    { value: 100, label: '100%' },
                                                ]}
                                            />
                                            <LemonInput
                                                type="number"
                                                min={0}
                                                max={100}
                                                value={group.rollout_percentage ?? 100}
                                                step={0.01}
                                                onChange={(value) => {
                                                    const raw = value ? parseFloat(value.toString()) : 0
                                                    const numValue = Math.round(raw * 100) / 100
                                                    updateConditionSet(index, Math.min(100, Math.max(0, numValue)))
                                                }}
                                                suffix={<span>%</span>}
                                                className="w-20"
                                            />
                                        </div>
                                        {group.sort_key && affectedCounts[group.sort_key] !== undefined ? (
                                            <div className="text-xs text-muted mt-2">
                                                {(() => {
                                                    const affected = group.sort_key
                                                        ? affectedCounts[group.sort_key]
                                                        : undefined
                                                    const total = group.sort_key
                                                        ? totalCounts[group.sort_key]
                                                        : undefined
                                                    const rolloutPct = Number.isNaN(group.rollout_percentage)
                                                        ? 0
                                                        : (group.rollout_percentage ?? 100)

                                                    if (affected === undefined || affected < 0 || total === undefined) {
                                                        return null
                                                    }

                                                    const receivingFlag = Math.floor(
                                                        (affected * clamp(rolloutPct, 0, 100)) / 100
                                                    )
                                                    if (rolloutPct === 100) {
                                                        return (
                                                            <>
                                                                <b>{humanFriendlyNumber(affected)}</b> of{' '}
                                                                {humanFriendlyNumber(total)} {resolvedTargetName} match
                                                                these filters
                                                            </>
                                                        )
                                                    }
                                                    return (
                                                        <>
                                                            Will match ~<b>{humanFriendlyNumber(receivingFlag)}</b> of{' '}
                                                            {humanFriendlyNumber(total)} {resolvedTargetName} (
                                                            {rolloutPct}% of {humanFriendlyNumber(affected)} matching
                                                            the filters)
                                                        </>
                                                    )
                                                })()}
                                                {(group.aggregation_group_type_index ??
                                                    releaseFilters.aggregation_group_type_index) == null && (
                                                    <Tooltip
                                                        title={
                                                            <>
                                                                A user may have{' '}
                                                                <Link
                                                                    to="https://posthog.com/docs/data/persons#duplicate-person-profiles"
                                                                    target="_blank"
                                                                >
                                                                    multiple profiles
                                                                </Link>
                                                            </>
                                                        }
                                                        interactive
                                                    >
                                                        <IconInfo className="text-muted text-xs ml-0.5" />
                                                    </Tooltip>
                                                )}
                                            </div>
                                        ) : (
                                            <div className="text-xs text-muted mt-2 flex items-center gap-1">
                                                <Spinner className="text-sm" /> Calculating affected{' '}
                                                {resolvedTargetName}…
                                            </div>
                                        )}
                                    </div>

                                    {variants && variants.length > 0 && (
                                        <div className="flex items-center gap-2 flex-wrap text-sm text-muted">
                                            <span className="flex items-center gap-1">
                                                <span className="font-medium text-default">Optional override</span>
                                                <Tooltip
                                                    title={
                                                        <>
                                                            Force all matching {resolvedTargetName} to receive a
                                                            specific variant.{' '}
                                                            <Link
                                                                to="https://posthog.com/docs/feature-flags/testing#method-1-assign-a-user-a-specific-flag-value"
                                                                target="_blank"
                                                            >
                                                                Learn more
                                                            </Link>
                                                        </>
                                                    }
                                                >
                                                    <IconInfo className="text-base" />
                                                </Tooltip>
                                            </span>
                                            <span>Set variant for all {resolvedTargetName} in this set to</span>
                                            <LemonSelect
                                                placeholder="Select variant"
                                                allowClear={true}
                                                value={group.variant ?? null}
                                                onChange={(value) =>
                                                    updateConditionSet(index, undefined, undefined, value)
                                                }
                                                options={variants.map((variant) => ({
                                                    label: variant.key,
                                                    value: variant.key,
                                                }))}
                                                size="small"
                                                data-attr="feature-flags-variant-override-select"
                                            />
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}
                    </div>
                </div>
                {totalGroups > 1 && (
                    <div className="flex flex-col items-center pr-2">
                        {isDragDropEnabled && (
                            <FeatureFlagConditionDragHandle
                                listeners={listeners}
                                attributes={attributes}
                                setActivatorNodeRef={setActivatorNodeRef}
                                hasMultipleConditions={true}
                            />
                        )}
                        <div className="flex flex-row gap-0.5 w-6 justify-center">
                            {index > 0 && (
                                <LemonButton
                                    icon={<IconArrowUp />}
                                    size="xsmall"
                                    noPadding
                                    tooltip="Move up"
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        onMoveUp()
                                    }}
                                />
                            )}
                            {index < totalGroups - 1 && (
                                <LemonButton
                                    icon={<IconArrowDown />}
                                    size="xsmall"
                                    noPadding
                                    tooltip="Move down"
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        onMoveDown()
                                    }}
                                />
                            )}
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}

export function FeatureFlagReleaseConditionsCollapsible({
    id,
    flagId,
    filters,
    onChange,
    readOnly,
    variants,
    isDisabled,
    bucketingIdentifier,
    onBucketingIdentifierChange,
    evaluationRuntime,
    hideMatchOptions,
}: FeatureFlagReleaseConditionsCollapsibleProps): JSX.Element {
    const releaseConditionsLogic = featureFlagReleaseConditionsLogic({
        id,
        readOnly,
        filters,
        onChange,
    })

    const {
        filterGroups,
        filtersTaxonomicOptions,
        affectedCounts,
        totalCounts,
        aggregationTargetName,
        taxonomicGroupTypesForCondition,
        filters: releaseFilters,
        groupTypes,
        openConditions,
        properties,
        isMixedTargeting,
        mixedGroupTypeIndex,
        isAnyItemDragging,
        draggedGroup,
    } = useValues(releaseConditionsLogic)

    const { featureFlags } = useValues(featureFlagLogic)
    const isDragDropEnabled = !!featureFlags[FEATURE_FLAGS.FEATURE_FLAG_DRAG_DROP_CONDITIONS]
    const isMixedTargetingEnabled = !!featureFlags[FEATURE_FLAGS.FEATURE_FLAG_MIXED_TARGETING]

    // Ref map for focus management
    const optionRefs = useRef<Record<string, HTMLDivElement | null>>({})

    const groupTypeValues = Array.from(groupTypes.values()) as GroupType[]

    const {
        updateConditionSet,
        removeConditionSet,
        addConditionSet,
        duplicateConditionSet,
        moveConditionSetUp,
        moveConditionSetDown,
        reorderConditionSets,
        setAggregationGroupTypeIndex,
        setConditionAggregation,
        setOpenConditions,
        setIsMixedTargeting,
        switchToMixedTargeting,
        setMixedGroupTypeIndex,
        setIsAnyItemDragging,
        setDraggedGroup,
    } = useActions(releaseConditionsLogic)

    const handleAddConditionSet = (): void => {
        addConditionSet(uuidv4())
    }

    const sensors = useSensors(
        useSensor(PointerSensor, {
            activationConstraint: { distance: 8 },
        }),
        useSensor(KeyboardSensor)
    )

    const handleDragStart = (event: DragStartEvent): void => {
        setIsAnyItemDragging(true)

        // Find the group being dragged
        const draggedItem = filterGroups.find(
            (group: FeatureFlagGroupType) => group.sort_key === String(event.active.id)
        )
        setDraggedGroup(draggedItem || null)
    }

    const handleDragEnd = (event: DragEndEvent): void => {
        const { active, over } = event
        if (over && active.id !== over.id) {
            reorderConditionSets(String(active.id), String(over.id))
        }
        setIsAnyItemDragging(false)
        setDraggedGroup(null)
    }

    const collapseRef = useRef<HTMLDivElement>(null)

    const handleOpenConditionsChange = (newKeys: string[]): void => {
        // Find newly opened panels
        const newlyOpened = newKeys.filter((key) => !openConditions.includes(key))
        setOpenConditions(newKeys)

        // Scroll to first newly opened panel after it expands
        if (newlyOpened.length > 0 && collapseRef.current) {
            // Extract the index from the key (format: "condition-{sort_key}")
            const openedKey = newlyOpened[0]
            const panelIndex = filterGroups.findIndex(
                (g: FeatureFlagGroupType) => `condition-${g.sort_key!}` === openedKey
            )

            setTimeout(() => {
                // Find the panel by its position in the collapse
                const panels = collapseRef.current?.querySelectorAll('.LemonCollapse__panel')
                if (panels && panels[panelIndex]) {
                    panels[panelIndex].scrollIntoView({ behavior: 'smooth', block: 'start' })
                }
            }, 150)
        }
    }

    if (readOnly) {
        return (
            <div className="flex flex-col gap-2">
                <LemonLabel>Release conditions</LemonLabel>
                {filterGroups.map((group: FeatureFlagGroupType, index: number) => {
                    // Use description if available, otherwise summarize the filters
                    const summary =
                        group.description ||
                        summarizeProperties(
                            group.properties || [],
                            aggregationTargetName(group.aggregation_group_type_index)
                        )
                    const rollout = group.rollout_percentage ?? 100
                    return (
                        <div key={group.sort_key} className="flex flex-col gap-1">
                            {index > 0 && <div className="text-xs text-muted text-center">OR</div>}
                            <div className="rounded border p-3 bg-bg-light">
                                <div className="text-sm flex items-center justify-between">
                                    <div className="flex items-center gap-2">
                                        <span className="font-medium text-xs bg-bg-light rounded px-1.5 py-0.5">
                                            {index + 1}
                                        </span>
                                        <span>{summary}</span>
                                    </div>
                                    <span className="text-muted">
                                        ({rollout}%{group.variant && ` · ${group.variant}`})
                                    </span>
                                </div>
                            </div>
                        </div>
                    )
                })}
            </div>
        )
    }

    const showGroupsOptions = groupTypes.size > 0

    // Compute current selected option (shared between keyboard navigation and selection rendering)
    const currentSelected = isMixedTargeting
        ? 'mixed'
        : releaseFilters.aggregation_group_type_index != null
          ? 'group'
          : bucketingIdentifier === FeatureFlagBucketingIdentifier.DEVICE_ID
            ? 'device'
            : 'user'

    // Handler for option selection logic (shared by click and keyboard events)
    const selectMatchByOption = (value: string): void => {
        if (value === 'user') {
            setIsMixedTargeting(false)
            setAggregationGroupTypeIndex(null)
            onBucketingIdentifierChange?.(FeatureFlagBucketingIdentifier.DISTINCT_ID)
        } else if (value === 'device') {
            setIsMixedTargeting(false)
            setAggregationGroupTypeIndex(null)
            onBucketingIdentifierChange?.(FeatureFlagBucketingIdentifier.DEVICE_ID)
        } else if (value === 'group') {
            setIsMixedTargeting(false)
            const firstGroupType = groupTypeValues[0]
            if (firstGroupType) {
                setAggregationGroupTypeIndex(firstGroupType.group_type_index)
            }
            onBucketingIdentifierChange?.(null)
        } else if (value === 'mixed') {
            switchToMixedTargeting()
            onBucketingIdentifierChange?.(null)
        }
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
                <LemonLabel>Release conditions</LemonLabel>
            </div>
            <p className="text-xs text-muted mb-2">
                Target users for this flag. Conditions are evaluated top to bottom – the first match wins. A condition
                matches when all property filters pass AND the target falls within the rollout percentage.
            </p>

            {isDisabled && (
                <LemonBanner type="info" className="mb-3">
                    This flag is currently <b>disabled</b>. These release conditions won't take effect until you enable
                    it.
                </LemonBanner>
            )}

            <FeatureFlagConditionWarning properties={properties} evaluationRuntime={evaluationRuntime} />

            {flagId && <IntentWarningsBanner flagId={flagId} />}

            {!hideMatchOptions && (showGroupsOptions || onBucketingIdentifierChange) && (
                <div>
                    <LemonLabel
                        className="mb-2"
                        id="match-by-label"
                        info="Changing match criteria may remove existing variants or payloads."
                    >
                        Match by
                    </LemonLabel>
                    <div
                        role="radiogroup"
                        aria-labelledby="match-by-label"
                        className="flex flex-wrap gap-2"
                        data-attr="feature-flag-aggregation-filter"
                        onKeyDown={(e) => {
                            // Handle arrow key navigation for radio group
                            if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) {
                                e.preventDefault()
                                const options = [
                                    'user',
                                    ...(onBucketingIdentifierChange ? ['device'] : []),
                                    ...(showGroupsOptions ? ['group'] : []),
                                    ...(showGroupsOptions && isMixedTargetingEnabled ? ['mixed'] : []),
                                ]

                                const currentIndex = options.indexOf(currentSelected)
                                let nextIndex = currentIndex

                                if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') {
                                    nextIndex = currentIndex > 0 ? currentIndex - 1 : options.length - 1
                                } else if (e.key === 'ArrowDown' || e.key === 'ArrowRight') {
                                    nextIndex = currentIndex < options.length - 1 ? currentIndex + 1 : 0
                                }

                                selectMatchByOption(options[nextIndex])

                                // Focus the newly selected option
                                optionRefs.current[options[nextIndex]]?.focus()
                            }
                        }}
                    >
                        {[
                            {
                                value: 'user',
                                icon: <IconPerson className="text-base shrink-0" />,
                                label: 'User',
                                description: 'Stable assignment for logged-in users based on their distinct ID.',
                            },
                            ...(onBucketingIdentifierChange
                                ? [
                                      {
                                          value: 'device',
                                          icon: <IconLaptop className="text-base shrink-0" />,
                                          label: 'Device',
                                          description:
                                              'Stable assignment per device. Good fit for experiments on anonymous users.',
                                          learnMoreUrl: 'https://posthog.com/docs/feature-flags/device-bucketing',
                                      },
                                  ]
                                : []),
                            ...(showGroupsOptions
                                ? [
                                      {
                                          value: 'group',
                                          icon: <IconPeople className="text-base shrink-0" />,
                                          label: 'Group',
                                          description:
                                              'Stable assignment for everyone in an organization, company, or other custom group type.',
                                      },
                                  ]
                                : []),
                            ...(showGroupsOptions && isMixedTargetingEnabled
                                ? [
                                      {
                                          value: 'mixed',
                                          icon: <IconBalance className="text-base shrink-0" />,
                                          label: 'User & Group',
                                          description:
                                              'Mix user and group targeting across condition sets. Each condition set picks its own targeting type.',
                                          badge: { type: 'highlight' as const, text: 'NEW' },
                                      },
                                  ]
                                : []),
                        ].map((option) => {
                            const isSelected = option.value === currentSelected

                            return (
                                <div
                                    key={option.value}
                                    ref={(el) => {
                                        optionRefs.current[option.value] = el
                                    }}
                                    role="radio"
                                    aria-checked={isSelected}
                                    tabIndex={isSelected ? 0 : -1}
                                    className={`rounded p-3 cursor-pointer transition-colors flex-1 min-w-0 ${
                                        isSelected
                                            ? 'bg-accent-highlight-light border-2 border-accent'
                                            : 'border bg-surface-primary border-primary hover:bg-fill-button-tertiary-hover'
                                    }`}
                                    onClick={() => selectMatchByOption(option.value)}
                                    onKeyDown={(e) => {
                                        if (e.key === 'Enter' || e.key === ' ') {
                                            e.preventDefault()
                                            selectMatchByOption(option.value)
                                        }
                                    }}
                                    data-attr={`feature-flag-aggregation-${option.value}`}
                                >
                                    <div className="flex flex-col gap-1">
                                        <div className="flex items-center gap-1.5">
                                            {option.icon}
                                            <span className="text-sm font-medium flex-1 truncate" title={option.label}>
                                                {option.label}
                                            </span>
                                            {option.badge && (
                                                <LemonTag type={option.badge.type} size="small">
                                                    {option.badge.text}
                                                </LemonTag>
                                            )}
                                            {isSelected && <IconCheckCircle className="text-accent text-sm shrink-0" />}
                                        </div>
                                        <div className="text-xs text-muted">
                                            {option.description}
                                            {option.learnMoreUrl && (
                                                <>
                                                    {' '}
                                                    <Link
                                                        to={option.learnMoreUrl}
                                                        target="_blank"
                                                        onClick={(e) => e.stopPropagation()}
                                                    >
                                                        Learn more
                                                    </Link>
                                                </>
                                            )}
                                        </div>
                                        {/* Group type selector for selected group option */}
                                        {option.value === 'group' &&
                                            isSelected &&
                                            releaseFilters.aggregation_group_type_index != null &&
                                            !isMixedTargeting &&
                                            (groupTypeValues.length > 1 ? (
                                                <div onClick={(e) => e.stopPropagation()}>
                                                    <LemonSelect
                                                        size="xsmall"
                                                        dropdownMatchSelectWidth={false}
                                                        data-attr="feature-flag-group-type-select"
                                                        value={releaseFilters.aggregation_group_type_index}
                                                        onChange={(value) => {
                                                            if (value != null) {
                                                                setAggregationGroupTypeIndex(value)
                                                            }
                                                        }}
                                                        options={groupTypeValues.map((groupType) => ({
                                                            value: groupType.group_type_index,
                                                            label: groupType.group_type,
                                                        }))}
                                                    />
                                                </div>
                                            ) : (
                                                <span className="text-xs font-medium">
                                                    {groupTypeValues[0]?.group_type}
                                                </span>
                                            ))}
                                        {/* Mixed group type selector */}
                                        {option.value === 'mixed' &&
                                            isSelected &&
                                            isMixedTargeting &&
                                            groupTypeValues.length > 1 && (
                                                <div onClick={(e) => e.stopPropagation()}>
                                                    <LemonSelect
                                                        size="xsmall"
                                                        dropdownMatchSelectWidth={false}
                                                        data-attr="feature-flag-mixed-group-type-select"
                                                        value={mixedGroupTypeIndex}
                                                        onChange={(value) => {
                                                            if (value != null) {
                                                                setMixedGroupTypeIndex(value)
                                                            }
                                                        }}
                                                        options={groupTypeValues.map((groupType) => ({
                                                            value: groupType.group_type_index,
                                                            label: groupType.group_type,
                                                        }))}
                                                    />
                                                </div>
                                            )}
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                </div>
            )}

            {filterGroups.length > 1 ? (
                <div className="relative mt-4">
                    {/* Expand/collapse controls positioned on top border */}
                    <div className="absolute top-0 right-4 transform -translate-y-1/2 z-10">
                        <div className="flex gap-2 bg-bg-light px-2">
                            {openConditions.length < filterGroups.length && (
                                <LemonButton
                                    size="xsmall"
                                    type="tertiary"
                                    icon={<IconExpand />}
                                    onClick={() => {
                                        const allConditionKeys = filterGroups.map(
                                            (group: FeatureFlagGroupType) => `condition-${group.sort_key!}`
                                        )
                                        handleOpenConditionsChange(allConditionKeys)
                                    }}
                                    data-attr="expand-all-conditions"
                                >
                                    Expand all
                                </LemonButton>
                            )}
                            {openConditions.length > 0 && (
                                <LemonButton
                                    size="xsmall"
                                    type="tertiary"
                                    icon={<IconCollapse />}
                                    onClick={() => handleOpenConditionsChange([])}
                                    data-attr="collapse-all-conditions"
                                >
                                    Collapse all
                                </LemonButton>
                            )}
                        </div>
                    </div>

                    {/* Rounded border box containing conditions */}
                    <div className="border rounded p-4" ref={collapseRef}>
                        {isDragDropEnabled ? (
                            <DndContext
                                sensors={sensors}
                                collisionDetection={rectIntersection}
                                onDragStart={handleDragStart}
                                onDragEnd={handleDragEnd}
                                onDragCancel={() => {
                                    setIsAnyItemDragging(false)
                                    setDraggedGroup(null)
                                }}
                            >
                                <SortableContext
                                    items={filterGroups.map((group: FeatureFlagGroupType) => group.sort_key!)}
                                    strategy={verticalListSortingStrategy}
                                >
                                    {filterGroups.map((group: FeatureFlagGroupType, index: number) => (
                                        <React.Fragment key={`fragment-${group.sort_key!}`}>
                                            {index > 0 && (
                                                <div className="text-xs font-medium text-muted uppercase tracking-wide text-center w-full py-2">
                                                    or
                                                </div>
                                            )}
                                            <DraggableCondition
                                                key={`condition-${group.sort_key!}`}
                                                group={group as FeatureFlagGroupTypeWithSortKey}
                                                index={index}
                                                totalGroups={filterGroups.length}
                                                affectedCounts={affectedCounts}
                                                totalCounts={totalCounts}
                                                aggregationTargetName={aggregationTargetName}
                                                taxonomicGroupTypesForCondition={taxonomicGroupTypesForCondition}
                                                groupTypes={groupTypes}
                                                setConditionAggregation={setConditionAggregation}
                                                isMixedTargetingEnabled={isMixedTargeting}
                                                mixedGroupTypeIndex={mixedGroupTypeIndex}
                                                onMoveUp={() => moveConditionSetUp(index)}
                                                onMoveDown={() => moveConditionSetDown(index)}
                                                onDuplicate={() => duplicateConditionSet(index)}
                                                onRemove={() => removeConditionSet(index)}
                                                updateConditionSet={updateConditionSet}
                                                filtersTaxonomicOptions={filtersTaxonomicOptions}
                                                releaseFilters={releaseFilters}
                                                variants={variants}
                                                openConditions={openConditions}
                                                handleOpenConditionsChange={handleOpenConditionsChange}
                                                flagId={flagId}
                                                id={id || 'feature-flag-conditions'}
                                                isAnyItemDragging={isAnyItemDragging}
                                            />
                                        </React.Fragment>
                                    ))}
                                </SortableContext>
                                <DragOverlay>
                                    {draggedGroup ? (
                                        <div
                                            className="border rounded bg-bg-light"
                                            style={{ opacity: 0.9, boxShadow: '0 8px 25px rgba(0, 0, 0, 0.15)' }}
                                        >
                                            <div className="flex items-center justify-between w-full p-3">
                                                <div className="flex items-start gap-2 min-w-0">
                                                    <span className="font-medium text-xs bg-bg-light rounded px-1.5 py-0.5 shrink-0">
                                                        {filterGroups.findIndex(
                                                            (g: FeatureFlagGroupType) =>
                                                                g.sort_key === draggedGroup.sort_key
                                                        ) + 1}
                                                    </span>
                                                    <span className="text-sm break-all">
                                                        {draggedGroup.description ||
                                                            summarizeProperties(
                                                                draggedGroup.properties || [],
                                                                aggregationTargetName(
                                                                    draggedGroup.aggregation_group_type_index
                                                                )
                                                            )}
                                                    </span>
                                                </div>
                                                <div className="flex items-center gap-2 shrink-0">
                                                    <span className="text-sm text-muted mr-2">
                                                        ({draggedGroup.rollout_percentage ?? 100}%
                                                        {draggedGroup.variant && ` · ${draggedGroup.variant}`})
                                                    </span>
                                                </div>
                                            </div>
                                        </div>
                                    ) : null}
                                </DragOverlay>
                            </DndContext>
                        ) : (
                            // Fallback to non-draggable conditions when feature flag is disabled
                            filterGroups.map((group: FeatureFlagGroupType, index: number) => (
                                <React.Fragment key={`fragment-${group.sort_key!}`}>
                                    {index > 0 && (
                                        <div className="text-xs font-medium text-muted uppercase tracking-wide text-center w-full py-2">
                                            or
                                        </div>
                                    )}
                                    <StaticCondition
                                        key={`condition-${group.sort_key!}`}
                                        group={group as FeatureFlagGroupTypeWithSortKey}
                                        index={index}
                                        totalGroups={filterGroups.length}
                                        affectedCounts={affectedCounts}
                                        totalCounts={totalCounts}
                                        aggregationTargetName={aggregationTargetName}
                                        taxonomicGroupTypesForCondition={taxonomicGroupTypesForCondition}
                                        groupTypes={groupTypes}
                                        setConditionAggregation={setConditionAggregation}
                                        isMixedTargetingEnabled={isMixedTargeting}
                                        mixedGroupTypeIndex={mixedGroupTypeIndex}
                                        onMoveUp={() => moveConditionSetUp(index)}
                                        onMoveDown={() => moveConditionSetDown(index)}
                                        onDuplicate={() => duplicateConditionSet(index)}
                                        onRemove={() => removeConditionSet(index)}
                                        updateConditionSet={updateConditionSet}
                                        filtersTaxonomicOptions={filtersTaxonomicOptions}
                                        releaseFilters={releaseFilters}
                                        variants={variants}
                                        openConditions={openConditions}
                                        handleOpenConditionsChange={handleOpenConditionsChange}
                                        flagId={flagId}
                                        id={id || 'feature-flag-conditions'}
                                        isAnyItemDragging={false}
                                    />
                                </React.Fragment>
                            ))
                        )}
                    </div>
                </div>
            ) : (
                <div ref={collapseRef}>
                    {isDragDropEnabled ? (
                        <DndContext
                            sensors={sensors}
                            collisionDetection={rectIntersection}
                            onDragStart={handleDragStart}
                            onDragEnd={handleDragEnd}
                            onDragCancel={() => {
                                setIsAnyItemDragging(false)
                                setDraggedGroup(null)
                            }}
                        >
                            <SortableContext
                                items={filterGroups.map((group: FeatureFlagGroupType) => group.sort_key!)}
                                strategy={verticalListSortingStrategy}
                            >
                                {filterGroups.map((group: FeatureFlagGroupType, index: number) => (
                                    <DraggableCondition
                                        key={`condition-${group.sort_key!}`}
                                        group={group as FeatureFlagGroupTypeWithSortKey}
                                        index={index}
                                        totalGroups={filterGroups.length}
                                        affectedCounts={affectedCounts}
                                        totalCounts={totalCounts}
                                        aggregationTargetName={aggregationTargetName}
                                        taxonomicGroupTypesForCondition={taxonomicGroupTypesForCondition}
                                        groupTypes={groupTypes}
                                        setConditionAggregation={setConditionAggregation}
                                        isMixedTargetingEnabled={isMixedTargeting}
                                        mixedGroupTypeIndex={mixedGroupTypeIndex}
                                        onMoveUp={() => moveConditionSetUp(index)}
                                        onMoveDown={() => moveConditionSetDown(index)}
                                        onDuplicate={() => duplicateConditionSet(index)}
                                        onRemove={() => removeConditionSet(index)}
                                        updateConditionSet={updateConditionSet}
                                        filtersTaxonomicOptions={filtersTaxonomicOptions}
                                        releaseFilters={releaseFilters}
                                        variants={variants}
                                        openConditions={openConditions}
                                        handleOpenConditionsChange={handleOpenConditionsChange}
                                        flagId={flagId}
                                        id={id || 'feature-flag-conditions'}
                                        isAnyItemDragging={isAnyItemDragging}
                                    />
                                ))}
                            </SortableContext>
                        </DndContext>
                    ) : (
                        filterGroups.map((group: FeatureFlagGroupType, index: number) => (
                            <StaticCondition
                                key={`condition-${group.sort_key!}`}
                                group={group as FeatureFlagGroupTypeWithSortKey}
                                index={index}
                                totalGroups={filterGroups.length}
                                affectedCounts={affectedCounts}
                                totalCounts={totalCounts}
                                aggregationTargetName={aggregationTargetName}
                                taxonomicGroupTypesForCondition={taxonomicGroupTypesForCondition}
                                groupTypes={groupTypes}
                                setConditionAggregation={setConditionAggregation}
                                isMixedTargetingEnabled={isMixedTargeting}
                                mixedGroupTypeIndex={mixedGroupTypeIndex}
                                onMoveUp={() => moveConditionSetUp(index)}
                                onMoveDown={() => moveConditionSetDown(index)}
                                onDuplicate={() => duplicateConditionSet(index)}
                                onRemove={() => removeConditionSet(index)}
                                updateConditionSet={updateConditionSet}
                                filtersTaxonomicOptions={filtersTaxonomicOptions}
                                releaseFilters={releaseFilters}
                                variants={variants}
                                openConditions={openConditions}
                                handleOpenConditionsChange={handleOpenConditionsChange}
                                flagId={flagId}
                                id={id || 'feature-flag-conditions'}
                                isAnyItemDragging={false}
                            />
                        ))
                    )}
                </div>
            )}

            <LemonButton type="secondary" icon={<IconPlus />} onClick={handleAddConditionSet}>
                Add condition set
            </LemonButton>
        </div>
    )
}
