import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCopy, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonInput, LemonLabel, LemonSelect, Spinner } from '@posthog/lemon-ui'

import { allOperatorsToHumanName } from 'lib/components/DefinitionPopover/utils'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isPropertyFilterWithOperator } from 'lib/components/PropertyFilters/utils'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { humanFriendlyNumber } from 'lib/utils'
import { clamp } from 'lib/utils'

import { AnyPropertyFilter, FeatureFlagGroupType, PropertyFilterType } from '~/types'

import {
    FeatureFlagReleaseConditionsLogicProps,
    featureFlagReleaseConditionsLogic,
} from './featureFlagReleaseConditionsLogic'

interface FeatureFlagReleaseConditionsCollapsibleProps extends FeatureFlagReleaseConditionsLogicProps {
    readOnly?: boolean
}

function summarizeProperties(properties: AnyPropertyFilter[], aggregationTargetName: string): string {
    if (!properties || properties.length === 0) {
        // Capitalize first letter of aggregation target name
        const capitalizedTarget = aggregationTargetName.charAt(0).toUpperCase() + aggregationTargetName.slice(1)
        return `All ${capitalizedTarget}`
    }

    const parts = properties.slice(0, 2).map((property) => {
        const key = property.type === PropertyFilterType.Cohort ? 'Cohort' : property.key || 'property'
        const operator = isPropertyFilterWithOperator(property) ? allOperatorsToHumanName(property.operator) : 'is'
        const value = Array.isArray(property.value)
            ? property.value.slice(0, 2).join(', ') + (property.value.length > 2 ? '...' : '')
            : property.value

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
    affectedUserCount: number | undefined
    totalUsers: number | null
    aggregationTargetName: string
    onMoveUp: () => void
    onMoveDown: () => void
    onDuplicate: () => void
    onRemove: () => void
}

function ConditionHeader({
    group,
    index,
    totalGroups,
    affectedUserCount,
    totalUsers,
    aggregationTargetName,
    onMoveUp,
    onMoveDown,
    onDuplicate,
    onRemove,
}: ConditionHeaderProps): JSX.Element {
    // Use description if available, otherwise summarize the filters
    const summary = group.description || summarizeProperties(group.properties || [], aggregationTargetName)
    const rollout = group.rollout_percentage ?? 100

    // Calculate the actual user count based on rollout percentage
    const actualUserCount =
        affectedUserCount !== undefined && affectedUserCount >= 0
            ? Math.floor((affectedUserCount * clamp(rollout, 0, 100)) / 100)
            : null

    return (
        <div className="flex items-center justify-between w-full">
            <div className="flex items-center gap-2">
                <span className="font-medium text-xs bg-bg-light rounded px-1.5 py-0.5">{index + 1}</span>
                <span className="text-sm truncate max-w-[300px]" title={summary}>
                    {summary}
                </span>
            </div>
            <div className="flex items-center gap-1">
                <span className="text-sm text-muted mr-2">
                    ({rollout}%
                    {actualUserCount !== null &&
                        totalUsers !== null &&
                        ` · ${humanFriendlyNumber(actualUserCount)} ${aggregationTargetName}`}
                    )
                </span>
                {totalGroups > 1 && (
                    <>
                        <LemonButton
                            icon={<IconArrowDown />}
                            size="xsmall"
                            noPadding
                            tooltip="Move down"
                            disabledReason={index >= totalGroups - 1 ? 'Already at bottom' : undefined}
                            onClick={(e) => {
                                e.stopPropagation()
                                onMoveDown()
                            }}
                        />
                        <LemonButton
                            icon={<IconArrowUp />}
                            size="xsmall"
                            noPadding
                            tooltip="Move up"
                            disabledReason={index === 0 ? 'Already at top' : undefined}
                            onClick={(e) => {
                                e.stopPropagation()
                                onMoveUp()
                            }}
                        />
                    </>
                )}
                <LemonButton
                    icon={<IconCopy />}
                    size="xsmall"
                    noPadding
                    tooltip="Duplicate condition set"
                    onClick={(e) => {
                        e.stopPropagation()
                        onDuplicate()
                    }}
                />
                {totalGroups > 1 && (
                    <LemonButton
                        icon={<IconTrash />}
                        size="xsmall"
                        noPadding
                        tooltip="Remove condition set"
                        onClick={(e) => {
                            e.stopPropagation()
                            onRemove()
                        }}
                    />
                )}
            </div>
        </div>
    )
}

export function FeatureFlagReleaseConditionsCollapsible({
    id,
    filters,
    onChange,
    readOnly,
}: FeatureFlagReleaseConditionsCollapsibleProps): JSX.Element {
    const releaseConditionsLogic = featureFlagReleaseConditionsLogic({
        id,
        readOnly,
        filters,
        onChange,
    })

    const {
        taxonomicGroupTypes,
        filterGroups,
        filtersTaxonomicOptions,
        affectedUsers,
        totalUsers,
        computeBlastRadiusPercentage,
        aggregationTargetName,
        filters: releaseFilters,
        groupTypes,
    } = useValues(releaseConditionsLogic)
    const {
        updateConditionSet,
        removeConditionSet,
        addConditionSet,
        duplicateConditionSet,
        moveConditionSetUp,
        moveConditionSetDown,
        setAggregationGroupTypeIndex,
    } = useActions(releaseConditionsLogic)

    const [openConditions, setOpenConditions] = useState<string[]>(filterGroups.length === 1 ? ['condition-0'] : [])

    const handleAddConditionSet = (): void => {
        addConditionSet()
        // Open the new condition set while keeping existing ones open
        const newIndex = filterGroups.length
        setOpenConditions((prev) => [...prev, `condition-${newIndex}`])
    }

    if (readOnly) {
        return (
            <div className="flex flex-col gap-2">
                <LemonLabel>Release conditions</LemonLabel>
                {filterGroups.map((group, index) => {
                    // Use description if available, otherwise summarize the filters
                    const summary =
                        group.description || summarizeProperties(group.properties || [], aggregationTargetName)
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
                                    <span className="text-muted">({rollout}%)</span>
                                </div>
                            </div>
                        </div>
                    )
                })}
            </div>
        )
    }

    const showGroupsOptions = groupTypes.size > 0

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
                <LemonLabel>Release conditions</LemonLabel>
            </div>
            <p className="text-xs text-muted mb-2">
                Specify users for flag release. Condition sets are evaluated top to bottom - the first matching set is
                used. A condition matches when all property filters pass AND the target falls within the rollout
                percentage.
            </p>

            {/* Match by selector */}
            {showGroupsOptions && (
                <div className="mb-2">
                    <LemonLabel className="mb-2">Match by</LemonLabel>
                    <LemonRadio
                        data-attr="feature-flag-aggregation-filter"
                        value={releaseFilters.aggregation_group_type_index != null ? 'group' : 'user'}
                        onChange={(value: string) => {
                            if (value === 'user') {
                                setAggregationGroupTypeIndex(null)
                            } else if (value === 'group') {
                                const firstGroupType = Array.from(groupTypes.values())[0]
                                if (firstGroupType) {
                                    setAggregationGroupTypeIndex(firstGroupType.group_type_index)
                                }
                            }
                        }}
                        options={[
                            {
                                value: 'user',
                                label: (
                                    <div>
                                        <div className="font-medium">User</div>
                                        <div className="text-xs text-muted">
                                            Stable assignment for logged-in users based on their distinct ID.
                                        </div>
                                    </div>
                                ),
                            },
                            {
                                value: 'group',
                                label: (
                                    <div>
                                        <div className="font-medium">Group</div>
                                        <div className="text-xs text-muted">
                                            Stable assignment for everyone in an organization, company, or other custom
                                            group type.
                                        </div>
                                    </div>
                                ),
                            },
                        ]}
                        radioPosition="top"
                    />
                    {releaseFilters.aggregation_group_type_index != null && groupTypes.size > 0 && (
                        <div className="mt-3 ml-6">
                            <LemonSelect
                                dropdownMatchSelectWidth={false}
                                data-attr="feature-flag-group-type-select"
                                value={releaseFilters.aggregation_group_type_index}
                                onChange={(value) => {
                                    if (value != null) {
                                        setAggregationGroupTypeIndex(value)
                                    }
                                }}
                                options={Array.from(groupTypes.values()).map((groupType) => ({
                                    value: groupType.group_type_index,
                                    label: groupType.group_type,
                                }))}
                            />
                        </div>
                    )}
                </div>
            )}

            <LemonCollapse
                multiple
                activeKeys={openConditions}
                onChange={setOpenConditions}
                panels={filterGroups.map((group, index) => ({
                    key: `condition-${index}`,
                    header: (
                        <ConditionHeader
                            group={group}
                            index={index}
                            totalGroups={filterGroups.length}
                            affectedUserCount={group.sort_key ? affectedUsers[group.sort_key] : undefined}
                            totalUsers={totalUsers}
                            aggregationTargetName={aggregationTargetName}
                            onMoveUp={() => moveConditionSetUp(index)}
                            onMoveDown={() => moveConditionSetDown(index)}
                            onDuplicate={() => duplicateConditionSet(index)}
                            onRemove={() => removeConditionSet(index)}
                        />
                    ),
                    className: index > 0 ? 'mt-1' : '',
                    content: (
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

                            <div>
                                <LemonLabel className="mb-1">Match filters</LemonLabel>
                                <PropertyFilters
                                    orFiltering={true}
                                    pageKey={`feature-flag-workflow-${id}-${index}`}
                                    propertyFilters={group?.properties}
                                    logicalRowDivider
                                    addText="Add filter"
                                    onChange={(properties) => updateConditionSet(index, undefined, properties)}
                                    taxonomicGroupTypes={taxonomicGroupTypes}
                                    taxonomicFilterOptionsFromProp={filtersTaxonomicOptions}
                                    hasRowOperator={false}
                                />
                            </div>

                            <div>
                                <LemonLabel className="mb-1">Rollout percentage</LemonLabel>
                                <div className="flex items-center gap-3">
                                    <div className="flex-1">
                                        <LemonSlider
                                            value={group.rollout_percentage ?? 100}
                                            onChange={(value) => updateConditionSet(index, value)}
                                            min={0}
                                            max={100}
                                            step={1}
                                        />
                                    </div>
                                    <LemonInput
                                        type="number"
                                        min={0}
                                        max={100}
                                        value={group.rollout_percentage ?? 100}
                                        onChange={(value) => {
                                            const numValue = value ? parseInt(value.toString()) : 0
                                            updateConditionSet(index, Math.min(100, Math.max(0, numValue)))
                                        }}
                                        suffix={<span>%</span>}
                                        className="w-20"
                                    />
                                </div>
                                {group.sort_key && affectedUsers[group.sort_key] !== undefined ? (
                                    <div className="text-xs text-muted mt-2">
                                        Will match approximately{' '}
                                        <b>
                                            {`${Math.max(
                                                computeBlastRadiusPercentage(
                                                    Number.isNaN(group.rollout_percentage)
                                                        ? 0
                                                        : group.rollout_percentage,
                                                    group.sort_key
                                                ).toPrecision(2) * 1,
                                                0
                                            )}%`}
                                        </b>{' '}
                                        {(() => {
                                            const affectedUserCount = group.sort_key
                                                ? affectedUsers[group.sort_key]
                                                : undefined
                                            if (
                                                affectedUserCount !== undefined &&
                                                affectedUserCount >= 0 &&
                                                totalUsers !== null
                                            ) {
                                                const rolloutPct = Number.isNaN(group.rollout_percentage)
                                                    ? 0
                                                    : (group.rollout_percentage ?? 100)
                                                return `(${humanFriendlyNumber(
                                                    Math.floor((affectedUserCount * clamp(rolloutPct, 0, 100)) / 100)
                                                )} / ${humanFriendlyNumber(totalUsers)})`
                                            }
                                            return ''
                                        })()}{' '}
                                        of total {aggregationTargetName}
                                    </div>
                                ) : (
                                    <div className="text-xs text-muted mt-2 flex items-center gap-1">
                                        <Spinner className="text-sm" /> Calculating affected {aggregationTargetName}…
                                    </div>
                                )}
                            </div>
                        </div>
                    ),
                }))}
            />

            <LemonButton type="secondary" icon={<IconPlus />} onClick={handleAddConditionSet} className="mt-1">
                Add condition set
            </LemonButton>
        </div>
    )
}
