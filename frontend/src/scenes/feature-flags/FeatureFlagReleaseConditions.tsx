import { InputNumber, Select } from 'antd'
import { useActions, useValues } from 'kea'
import { capitalizeFirstLetter, humanFriendlyNumber } from 'lib/utils'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { featureFlagLogic } from './featureFlagLogic'
import './FeatureFlag.scss'
import { IconCopy, IconDelete, IconPlus, IconSubArrowRight, IconErrorOutline } from 'lib/lemon-ui/icons'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { groupsModel } from '~/models/groupsModel'
import { GroupsIntroductionOption } from 'lib/introductions/GroupsIntroductionOption'
import { AnyPropertyFilter, FeatureFlagGroupType } from '~/types'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { urls } from 'scenes/urls'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { router } from 'kea-router'
import { INSTANTLY_AVAILABLE_PROPERTIES } from 'lib/constants'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { allOperatorsToHumanName } from 'lib/components/DefinitionPopover/utils'
import { cohortsModel } from '~/models/cohortsModel'
import { LemonSelect, Link } from '@posthog/lemon-ui'
import { isPropertyFilterWithOperator } from 'lib/components/PropertyFilters/utils'
import clsx from 'clsx'

interface FeatureFlagReadOnlyProps {
    readOnly?: boolean
    isSuper?: boolean
    excludeTitle?: boolean
}

export function FeatureFlagReleaseConditions({
    readOnly,
    isSuper,
    excludeTitle,
}: FeatureFlagReadOnlyProps): JSX.Element {
    const { showGroupsOptions, aggregationLabel } = useValues(groupsModel)
    const {
        aggregationTargetName,
        featureFlag,
        groupTypes,
        taxonomicGroupTypes,
        nonEmptyVariants,
        propertySelectErrors,
        computeBlastRadiusPercentage,
        affectedUsers,
        totalUsers,
    } = useValues(featureFlagLogic)
    const {
        setAggregationGroupTypeIndex,
        updateConditionSet,
        duplicateConditionSet,
        removeConditionSet,
        addConditionSet,
    } = useActions(featureFlagLogic)
    const { cohortsById } = useValues(cohortsModel)

    const filterGroups: FeatureFlagGroupType[] = isSuper
        ? featureFlag.filters.super_groups || []
        : featureFlag.filters.groups
    // :KLUDGE: Match by select only allows Select.Option as children, so render groups option directly rather than as a child
    const matchByGroupsIntroductionOption = GroupsIntroductionOption({ value: -2 })
    const hasNonInstantProperty = (properties: AnyPropertyFilter[]): boolean => {
        return !!properties.find(
            (property) => property.type === 'cohort' || !INSTANTLY_AVAILABLE_PROPERTIES.includes(property.key || '')
        )
    }

    const isEarlyAccessFeatureCondition = (group: FeatureFlagGroupType): boolean => {
        return !!(
            featureFlag.features?.length &&
            featureFlag.features?.length > 0 &&
            group.properties?.some((property) => property.key === '$feature_enrollment/' + featureFlag.key)
        )
    }

    const renderReleaseConditionGroup = (group: FeatureFlagGroupType, index: number): JSX.Element => {
        return (
            <div className="w-full" key={`${index}-${filterGroups.length}`}>
                {index > 0 && <div className="condition-set-separator">OR</div>}
                <div className={clsx('mb-4', 'border', 'rounded', 'p-4')}>
                    <div className="flex items-center justify-between">
                        <div className="flex items-center">
                            <span className="simple-tag tag-light-blue font-medium mr-2">Set {index + 1}</span>
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
                                <LemonButton
                                    icon={<IconCopy />}
                                    status="muted"
                                    noPadding
                                    onClick={() => duplicateConditionSet(index)}
                                />
                                {!isEarlyAccessFeatureCondition(group) && filterGroups.length > 1 && (
                                    <LemonButton
                                        icon={<IconDelete />}
                                        status="muted"
                                        noPadding
                                        onClick={() => removeConditionSet(index)}
                                    />
                                )}
                            </div>
                        )}
                    </div>
                    <LemonDivider className="my-3" />
                    {!readOnly && hasNonInstantProperty(group.properties || []) && (
                        <LemonBanner type="info" className="mt-3 mb-3">
                            These properties aren't immediately available on first page load for unidentified persons.
                            This feature flag requires that at least one event is sent prior to becoming available to
                            your product or website.{' '}
                            <Link to="https://posthog.com/docs/integrate/client/js#bootstrapping-flags" target="_blank">
                                {' '}
                                Learn more about how to make feature flags available instantly.
                            </Link>
                        </LemonBanner>
                    )}

                    {readOnly ? (
                        <>
                            {group.properties?.map((property, idx) => (
                                <>
                                    <div className="feature-flag-property-display" key={idx}>
                                        {idx === 0 ? (
                                            <LemonButton
                                                icon={<IconSubArrowRight className="arrow-right" />}
                                                status="muted"
                                                size="small"
                                            />
                                        ) : (
                                            <LemonButton
                                                icon={<span className="text-sm">&</span>}
                                                status="muted"
                                                size="small"
                                            />
                                        )}
                                        <span className="simple-tag tag-light-blue text-primary-alt">
                                            {property.type === 'cohort' ? 'Cohort' : property.key}{' '}
                                        </span>
                                        {isPropertyFilterWithOperator(property) ? (
                                            <span>{allOperatorsToHumanName(property.operator)} </span>
                                        ) : null}

                                        {property.type === 'cohort' ? (
                                            <Link
                                                to={urls.cohort(property.value)}
                                                target="_blank"
                                                className="simple-tag tag-light-blue text-primary-alt display-value"
                                            >
                                                {(property.value && cohortsById[property.value]?.name) ||
                                                    `ID ${property.value}`}
                                            </Link>
                                        ) : (
                                            [
                                                ...(Array.isArray(property.value) ? property.value : [property.value]),
                                            ].map((val, idx) => (
                                                <span
                                                    key={idx}
                                                    className="simple-tag tag-light-blue text-primary-alt display-value"
                                                >
                                                    {val}
                                                </span>
                                            ))
                                        )}
                                    </div>
                                </>
                            ))}
                        </>
                    ) : (
                        <div>
                            <PropertyFilters
                                orFiltering={true}
                                pageKey={`feature-flag-${featureFlag.id}-${index}-${filterGroups.length}-${
                                    featureFlag.filters.aggregation_group_type_index ?? ''
                                }`}
                                propertyFilters={group?.properties}
                                logicalRowDivider
                                addText="Add condition"
                                onChange={(properties) => updateConditionSet(index, undefined, properties)}
                                taxonomicGroupTypes={taxonomicGroupTypes}
                                hasRowOperator={false}
                                sendAllKeyUpdates
                                errorMessages={
                                    propertySelectErrors?.[index]?.properties?.some((message) => !!message.value)
                                        ? propertySelectErrors[index].properties?.map((message, index) => {
                                              return message.value ? (
                                                  <div
                                                      key={index}
                                                      className="text-danger flex items-center gap-1 text-sm"
                                                  >
                                                      <IconErrorOutline className="text-xl" /> {message.value}
                                                  </div>
                                              ) : (
                                                  <></>
                                              )
                                          })
                                        : null
                                }
                            />
                        </div>
                    )}
                    {(!readOnly || (readOnly && (group.properties?.length || 0) > 0)) && (
                        <LemonDivider className="my-3" />
                    )}
                    {readOnly ? (
                        <LemonTag
                            type={
                                filterGroups.length == 1
                                    ? group.rollout_percentage == null || group.rollout_percentage == 100
                                        ? 'highlight'
                                        : group.rollout_percentage == 0
                                        ? 'caution'
                                        : 'none'
                                    : 'none'
                            }
                        >
                            <div className="text-sm ">
                                Rolled out to{' '}
                                <b>{group.rollout_percentage != null ? group.rollout_percentage : 100}%</b> of{' '}
                                <b>{aggregationTargetName}</b> in this set.{' '}
                            </div>
                        </LemonTag>
                    ) : (
                        <div className="feature-flag-form-row gap-2">
                            <div className="flex items-center gap-1">
                                Roll out to{' '}
                                <InputNumber
                                    style={{ width: 100, marginLeft: 8, marginRight: 8 }}
                                    onChange={(value): void => {
                                        updateConditionSet(index, value)
                                    }}
                                    value={group.rollout_percentage != null ? group.rollout_percentage : 100}
                                    min={0}
                                    max={100}
                                    addonAfter="%"
                                />{' '}
                                of <b>{aggregationTargetName}</b> in this set.{' '}
                            </div>
                            <div>
                                Will match approximately{' '}
                                {affectedUsers[index] !== undefined ? (
                                    <b>
                                        {`${
                                            computeBlastRadiusPercentage(group.rollout_percentage, index).toPrecision(
                                                2
                                            ) * 1
                                            // Multiplying by 1 removes trailing zeros after the decimal
                                            // point added by toPrecision
                                        }% `}
                                    </b>
                                ) : (
                                    <Spinner className="mr-1" />
                                )}{' '}
                                {affectedUsers[index] && affectedUsers[index] >= 0 && totalUsers
                                    ? `(${humanFriendlyNumber(
                                          Math.floor((affectedUsers[index] * (group.rollout_percentage ?? 100)) / 100)
                                      )} / ${humanFriendlyNumber(totalUsers)})`
                                    : ''}{' '}
                                of total {aggregationTargetName}.
                            </div>
                        </div>
                    )}
                    {nonEmptyVariants.length > 0 && (
                        <>
                            <LemonDivider className="my-3" />
                            {readOnly ? (
                                <div>
                                    All <b>{aggregationTargetName}</b> in this set{' '}
                                    {group.variant ? (
                                        <>
                                            {' '}
                                            will be in variant <b>{group.variant}</b>
                                        </>
                                    ) : (
                                        <>have no variant override</>
                                    )}
                                </div>
                            ) : (
                                <div className="feature-flag-form-row">
                                    <div className="centered">
                                        <b>Optional override:</b> Set variant for all <b>{aggregationTargetName}</b> in
                                        this set to{' '}
                                        <LemonSelect
                                            placeholder="Select variant"
                                            allowClear={true}
                                            value={group.variant}
                                            onChange={(value) => updateConditionSet(index, undefined, undefined, value)}
                                            options={nonEmptyVariants.map((variant) => ({
                                                label: variant.key,
                                                value: variant.key,
                                            }))}
                                            data-attr="feature-flags-variant-override-select"
                                        />
                                    </div>
                                </div>
                            )}
                        </>
                    )}
                </div>
            </div>
        )
    }

    const renderSuperReleaseConditionGroup = (group: FeatureFlagGroupType, index: number): JSX.Element => {
        if (!readOnly) {
            return <></>
        }

        // TODO: EarlyAccessFeatureType is not the correct type for featureFlag.features, hence bypassing TS check
        const hasMatchingEarlyAccessFeature = featureFlag.features?.find((f: any) => f.flagKey === featureFlag.key)

        return (
            <div className="w-full" key={`${index}-${filterGroups.length}`}>
                {index > 0 && <div className="condition-set-separator">OR</div>}
                <div className={clsx('mb-4', 'border', 'rounded', 'p-4', 'FeatureConditionCard--border--highlight')}>
                    <div className="flex items-center justify-between">
                        <div className="flex items-center">
                            <div>
                                {group.properties?.length ? (
                                    <>
                                        Match <b>{aggregationTargetName}</b> against value set on{' '}
                                        <span className="simple-tag tag-light-blue text-primary-alt">
                                            {'$feature_enrollment/' + featureFlag.key}
                                        </span>
                                    </>
                                ) : (
                                    <>
                                        Condition set will match <b>all {aggregationTargetName}</b>
                                    </>
                                )}
                            </div>
                        </div>
                    </div>
                    <LemonDivider className="my-3" />

                    {(group.properties?.length || 0) > 0 && (
                        <>
                            <div className="feature-flag-property-display">
                                <LemonButton
                                    icon={<IconSubArrowRight className="arrow-right" />}
                                    status="muted"
                                    size="small"
                                />
                                <span>
                                    If null, default to <b>Release conditions</b>
                                </span>
                            </div>
                            <LemonDivider className="my-3" />
                        </>
                    )}
                    <div className="flex items-center justify-between">
                        <div />
                        <LemonButton
                            disabledReason={
                                !hasMatchingEarlyAccessFeature &&
                                'The matching Early Access Feature was not found. You can create it in the Early Access Management tab.'
                            }
                            aria-label="more"
                            data-attr={'feature-flag-feature-list-button'}
                            status="primary"
                            size="small"
                            onClick={() =>
                                featureFlag.features &&
                                featureFlag.features.length &&
                                router.actions.push(urls.earlyAccessFeature(featureFlag.features[0].id))
                            }
                        >
                            {hasMatchingEarlyAccessFeature ? 'View Early Access Feature' : 'No Early Access Feature'}
                        </LemonButton>
                    </div>
                </div>
            </div>
        )
    }

    return (
        <>
            <div className={`feature-flag-form-row ${excludeTitle && 'mb-2'}`}>
                <div data-attr="feature-flag-release-conditions" className="w-full">
                    {readOnly ? (
                        excludeTitle ? null : (
                            <h3 className="l3">{isSuper ? 'Super Release Conditions' : 'Release conditions'}</h3>
                        )
                    ) : (
                        <>
                            {!excludeTitle && (
                                <>
                                    <h3 className="l3">Release conditions</h3>
                                    <div className="text-muted mb-4">
                                        Specify the {aggregationTargetName} to which you want to release this flag. Note
                                        that condition sets are rolled out independently of each other.
                                    </div>
                                </>
                            )}
                        </>
                    )}
                    {!readOnly &&
                        !filterGroups.every(
                            (group) =>
                                filterGroups.filter((g) => g.variant === group.variant && g.variant !== null).length < 2
                        ) && (
                            <LemonBanner type="info" className="mt-3 mb-3">
                                Multiple variant overrides detected. We use the variant override for the first condition
                                set that matches.
                            </LemonBanner>
                        )}
                </div>
                {!readOnly && showGroupsOptions && (
                    <div className="centered">
                        Match by
                        <Select
                            value={
                                featureFlag.filters.aggregation_group_type_index != null
                                    ? featureFlag.filters.aggregation_group_type_index
                                    : -1
                            }
                            onChange={(value) => {
                                const groupTypeIndex = value !== -1 ? value : null
                                setAggregationGroupTypeIndex(groupTypeIndex)
                            }}
                            style={{ marginLeft: 8 }}
                            data-attr="feature-flag-aggregation-filter"
                            dropdownMatchSelectWidth={false}
                            dropdownAlign={{
                                // Align this dropdown by the right-hand-side of button
                                points: ['tr', 'br'],
                            }}
                        >
                            <Select.Option key={-1} value={-1}>
                                Users
                            </Select.Option>
                            {Array.from(groupTypes.values()).map((groupType) => (
                                <Select.Option key={groupType.group_type_index} value={groupType.group_type_index}>
                                    {capitalizeFirstLetter(aggregationLabel(groupType.group_type_index).plural)}
                                </Select.Option>
                            ))}
                            {matchByGroupsIntroductionOption}
                        </Select>
                    </div>
                )}
            </div>
            <div className="FeatureConditionCard">
                {filterGroups.map((group, index) =>
                    isSuper ? renderSuperReleaseConditionGroup(group, index) : renderReleaseConditionGroup(group, index)
                )}
            </div>
            {!readOnly && (
                <LemonButton type="secondary" className="mt-0 w-max" onClick={addConditionSet} icon={<IconPlus />}>
                    Add condition set
                </LemonButton>
            )}
        </>
    )
}
