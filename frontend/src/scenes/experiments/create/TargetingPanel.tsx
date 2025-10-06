import { useActions, useValues } from 'kea'

import { IconCopy, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput, LemonSelect, LemonSnack } from '@posthog/lemon-ui'

import { EditableField } from 'lib/components/EditableField/EditableField'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { INSTANTLY_AVAILABLE_PROPERTIES } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { IconArrowDown, IconArrowUp, IconSubArrowRight } from 'lib/lemon-ui/icons'
import { capitalizeFirstLetter, humanFriendlyNumber } from 'lib/utils'

import { groupsModel } from '~/models/groupsModel'
import { AnyPropertyFilter, FeatureFlagGroupType, PropertyFilterType } from '~/types'

import { TargetingPanelLogicProps, targetingPanelLogic } from './targetingPanelLogic'

export function TargetingPanel({ id, filters, onChange, readOnly = false }: TargetingPanelLogicProps): JSX.Element {
    const logic = targetingPanelLogic({ id, filters, onChange, readOnly })
    const {
        filters: currentFilters,
        taxonomicGroupTypes,
        affectedUsers,
        totalUsers,
        aggregationTargetName,
    } = useValues(logic)

    const {
        setAggregationGroupTypeIndex,
        updateConditionSet,
        duplicateConditionSet,
        removeConditionSet,
        addConditionSet,
        moveConditionSetUp,
        moveConditionSetDown,
    } = useActions(logic)

    const { showGroupsOptions, groupTypes, aggregationLabel } = useValues(groupsModel)
    const { computeBlastRadiusPercentage } = useValues(logic)

    const filterGroups: FeatureFlagGroupType[] = currentFilters?.groups || []

    const hasNonInstantProperty = (properties: AnyPropertyFilter[]): boolean => {
        return !!properties.find(
            (property) =>
                property.type === PropertyFilterType.Cohort ||
                !INSTANTLY_AVAILABLE_PROPERTIES.includes(property.key || '')
        )
    }

    const renderReleaseConditionGroup = (group: FeatureFlagGroupType, index: number): JSX.Element => {
        return (
            <div className="w-full" key={group.sort_key}>
                {index > 0 && <div className="mb-2 ml-2 text-xs font-semibold text-primary-alt my-1 py-0">OR</div>}
                <div className="border rounded p-4 bg-surface-primary">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center">
                            <LemonSnack className="mr-2">Set {index + 1}</LemonSnack>
                            <div>
                                {group.properties?.length ? (
                                    <>
                                        {readOnly ? (
                                            <>
                                                Match <b>{aggregationTargetName}</b> against <b>all</b> criteria
                                            </>
                                        ) : (
                                            <>
                                                Matching <b>{aggregationTargetName}</b> against the criteria
                                            </>
                                        )}
                                    </>
                                ) : (
                                    <>
                                        Condition set will match <b>all {aggregationTargetName}</b>
                                    </>
                                )}
                            </div>
                        </div>
                        {!readOnly && (
                            <div className="flex">
                                {filterGroups.length > 1 && (
                                    <div className="flex mr-2">
                                        <LemonButton
                                            icon={<IconArrowDown />}
                                            noPadding
                                            tooltip="Move condition set down in precedence"
                                            disabledReason={
                                                index === filterGroups.length - 1
                                                    ? 'Cannot move last condition set down'
                                                    : affectedUsers[index] === undefined ||
                                                        affectedUsers[index + 1] === undefined
                                                      ? 'Cannot move condition sets while calculating affected users'
                                                      : null
                                            }
                                            onClick={() => moveConditionSetDown(index)}
                                        />

                                        <LemonButton
                                            icon={<IconArrowUp />}
                                            noPadding
                                            tooltip="Move condition set up in precedence"
                                            disabledReason={
                                                index === 0
                                                    ? 'Cannot move first condition set up'
                                                    : affectedUsers[index] === undefined ||
                                                        affectedUsers[index - 1] === undefined
                                                      ? 'Cannot move condition sets while calculating affected users'
                                                      : null
                                            }
                                            onClick={() => moveConditionSetUp(index)}
                                        />
                                    </div>
                                )}
                                <LemonButton
                                    icon={<IconCopy />}
                                    noPadding
                                    tooltip="Duplicate condition set"
                                    onClick={() => duplicateConditionSet(index)}
                                />
                                {filterGroups.length > 1 && (
                                    <LemonButton
                                        icon={<IconTrash />}
                                        noPadding
                                        tooltip="Remove condition set"
                                        onClick={() => removeConditionSet(index)}
                                    />
                                )}
                            </div>
                        )}
                    </div>
                    {!readOnly && (
                        <div className="mt-3 max-w-md">
                            <EditableField
                                multiline
                                name="description"
                                value={group.description || ''}
                                placeholder="Description (optional)"
                                onSave={(value) => updateConditionSet(index, undefined, undefined, value)}
                                saveOnBlur={true}
                                maxLength={600}
                                data-attr={`condition-set-${index}-description`}
                                compactButtons
                            />
                        </div>
                    )}
                    {readOnly && group.description && <div className="mt-2 text-muted">{group.description}</div>}
                    <LemonDivider className="my-3" />
                    {!readOnly && hasNonInstantProperty(group.properties || []) && (
                        <LemonBanner type="info" className="mt-3 mb-3">
                            These properties aren't immediately available on first page load for unidentified persons.
                            This experiment requires that at least one event is sent prior to becoming available to your
                            product or website.
                        </LemonBanner>
                    )}
                    {readOnly ? (
                        <>
                            {group.properties?.map((property, idx) => (
                                <div className="flex flex-row flex-wrap gap-2 items-center mt-2" key={idx}>
                                    {idx === 0 ? (
                                        <LemonButton icon={<IconSubArrowRight className="mt-1 -mr-2" />} size="small" />
                                    ) : (
                                        <LemonButton icon={<span className="text-sm">&</span>} size="small" />
                                    )}
                                    <LemonSnack>
                                        {property.type === PropertyFilterType.Cohort ? 'Cohort' : property.key}
                                    </LemonSnack>
                                </div>
                            ))}
                        </>
                    ) : (
                        <div>
                            <PropertyFilters
                                orFiltering={true}
                                pageKey={`experiment-targeting-${id}-${group.sort_key}-${filterGroups.length}-${
                                    currentFilters.aggregation_group_type_index ?? ''
                                }`}
                                propertyFilters={group?.properties}
                                logicalRowDivider
                                addText="Add condition"
                                onChange={(properties) => updateConditionSet(index, undefined, properties)}
                                taxonomicGroupTypes={taxonomicGroupTypes}
                                hasRowOperator={false}
                                sendAllKeyUpdates
                                allowRelativeDateOptions
                                exactMatchFeatureFlagCohortOperators={true}
                                hideBehavioralCohorts={true}
                            />
                        </div>
                    )}
                    {(!readOnly || (readOnly && (group.properties?.length || 0) > 0)) && (
                        <LemonDivider className="my-3" />
                    )}
                    {readOnly ? (
                        <div className="text-sm">
                            Rolled out to{' '}
                            {group.rollout_percentage != null ? <b>{group.rollout_percentage}</b> : <b>100</b>}
                            <b>%</b>
                            <span> of </span>
                            <b>{aggregationTargetName}</b> <span>in this set.</span>
                        </div>
                    ) : (
                        <div className="flex flex-wrap items-center w-full gap-2">
                            <div className="flex flex-wrap items-center gap-1">
                                Roll out to{' '}
                                <LemonSlider
                                    value={group.rollout_percentage !== null ? group.rollout_percentage : 100}
                                    onChange={(value) => {
                                        updateConditionSet(index, value)
                                    }}
                                    min={0}
                                    max={100}
                                    step={1}
                                    className="ml-1.5 w-20"
                                />
                                <LemonInput
                                    data-attr="rollout-percentage"
                                    type="number"
                                    className="ml-2 mr-1.5 max-w-30"
                                    onChange={(value: number | undefined): void => {
                                        updateConditionSet(index, value === undefined ? 0 : value)
                                    }}
                                    value={group.rollout_percentage !== null ? group.rollout_percentage : 100}
                                    min={0}
                                    max={100}
                                    step="any"
                                    suffix={<span>%</span>}
                                />
                                of <b>{aggregationTargetName}</b> in this set. Will match approximately{' '}
                                {affectedUsers[index] !== undefined ? (
                                    <b>
                                        {`${Number(
                                            computeBlastRadiusPercentage(group.rollout_percentage, index).toPrecision(2)
                                        )}% `}
                                    </b>
                                ) : (
                                    <Spinner className="mr-1" />
                                )}{' '}
                                {(() => {
                                    const affectedUserCount = affectedUsers[index]
                                    if (
                                        affectedUserCount !== undefined &&
                                        affectedUserCount >= 0 &&
                                        totalUsers !== null
                                    ) {
                                        return `(${humanFriendlyNumber(
                                            Math.floor((affectedUserCount * (group.rollout_percentage ?? 100)) / 100)
                                        )} / ${humanFriendlyNumber(totalUsers)})`
                                    }
                                    return ''
                                })()}{' '}
                                <span>of total {aggregationTargetName}.</span>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        )
    }

    return (
        <div className="space-y-4">
            <div className="text-secondary mb-2">
                Specify {aggregationTargetName} for your experiment. Condition sets are evaluated top to bottom - the
                first matching set is used. A condition matches when all property filters pass AND the target falls
                within the rollout percentage.
            </div>

            {!readOnly && showGroupsOptions && (
                <div className="flex items-center gap-2">
                    Match by
                    <LemonSelect
                        dropdownMatchSelectWidth={false}
                        data-attr="experiment-aggregation-filter"
                        onChange={(value) => {
                            const groupTypeIndex = value !== -1 ? value : null
                            setAggregationGroupTypeIndex(groupTypeIndex)
                        }}
                        value={
                            currentFilters.aggregation_group_type_index != null
                                ? currentFilters.aggregation_group_type_index
                                : -1
                        }
                        options={[
                            { value: -1, label: 'Users' },
                            ...Array.from(groupTypes.values()).map((groupType) => ({
                                value: groupType.group_type_index,
                                label: capitalizeFirstLetter(aggregationLabel(groupType.group_type_index).plural),
                            })),
                        ]}
                    />
                </div>
            )}
            <div className="space-y-4">
                {filterGroups.map((group, index) => (
                    <div key={group.sort_key || index}>{renderReleaseConditionGroup(group, index)}</div>
                ))}
            </div>
            {!readOnly && (
                <LemonButton type="secondary" className="mt-0 w-max" onClick={addConditionSet} icon={<IconPlus />}>
                    Add condition set
                </LemonButton>
            )}
        </div>
    )
}
