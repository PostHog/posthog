import './FeatureFlag.scss'

import { IconCopy, IconPlus, IconTrash } from '@posthog/icons'
import { LemonInput, LemonSelect, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { allOperatorsToHumanName } from 'lib/components/DefinitionPopover/utils'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isPropertyFilterWithOperator } from 'lib/components/PropertyFilters/utils'
import { FEATURE_FLAGS, INSTANTLY_AVAILABLE_PROPERTIES } from 'lib/constants'
import { groupsAccessLogic, GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { GroupsIntroductionOption } from 'lib/introductions/GroupsIntroductionOption'
import { IconErrorOutline, IconOpenInNew, IconSubArrowRight } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { capitalizeFirstLetter, dateFilterToText, dateStringToComponents, humanFriendlyNumber } from 'lib/utils'
import { urls } from 'scenes/urls'

import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { AnyPropertyFilter, FeatureFlagGroupType } from '~/types'

import { featureFlagLogic } from './featureFlagLogic'
import {
    featureFlagReleaseConditionsLogic,
    FeatureFlagReleaseConditionsLogicProps,
} from './FeatureFlagReleaseConditionsLogic'

export function FeatureFlagReleaseConditions({
    id,
    readOnly,
    isSuper,
    excludeTitle,
    filters,
    onChange,
    hideMatchOptions,
}: FeatureFlagReleaseConditionsLogicProps & {
    hideMatchOptions?: boolean
    isSuper?: boolean
    excludeTitle?: boolean
}): JSX.Element {
    const releaseConditionsLogic = featureFlagReleaseConditionsLogic({
        id,
        readOnly,
        isSuper,
        excludeTitle,
        filters,
        onChange,
    })
    const {
        taxonomicGroupTypes,
        propertySelectErrors,
        computeBlastRadiusPercentage,
        affectedUsers,
        totalUsers,
        filtersTaxonomicOptions,
        enabledFeatures,
    } = useValues(releaseConditionsLogic)

    const {
        setAggregationGroupTypeIndex,
        updateConditionSet,
        duplicateConditionSet,
        removeConditionSet,
        addConditionSet,
    } = useActions(releaseConditionsLogic)

    const { showGroupsOptions, aggregationLabel } = useValues(groupsModel)
    const {
        aggregationTargetName,
        earlyAccessFeaturesList,
        hasEarlyAccessFeatures,
        featureFlagKey,
        groupTypes,
        nonEmptyVariants,
    } = useValues(featureFlagLogic)

    const { cohortsById } = useValues(cohortsModel)
    const { groupsAccessStatus } = useValues(groupsAccessLogic)

    const filterGroups: FeatureFlagGroupType[] = isSuper ? filters?.super_groups || [] : filters?.groups || []
    // :KLUDGE: Match by select only allows Select.Option as children, so render groups option directly rather than as a child
    const matchByGroupsIntroductionOption = GroupsIntroductionOption()
    const hasNonInstantProperty = (properties: AnyPropertyFilter[]): boolean => {
        return !!properties.find(
            (property) => property.type === 'cohort' || !INSTANTLY_AVAILABLE_PROPERTIES.includes(property.key || '')
        )
    }

    const isEarlyAccessFeatureCondition = (group: FeatureFlagGroupType): boolean => {
        return !!(
            hasEarlyAccessFeatures &&
            group.properties?.some((property) => property.key === '$feature_enrollment/' + featureFlagKey)
        )
    }

    const includeGroupsIntroductionOption = (): boolean =>
        [GroupsAccessStatus.HasAccess, GroupsAccessStatus.HasGroupTypes, GroupsAccessStatus.NoAccess].includes(
            groupsAccessStatus
        )

    const renderReleaseConditionGroup = (group: FeatureFlagGroupType, index: number): JSX.Element => {
        return (
            <div className="w-full" key={`${index}-${filterGroups.length}`}>
                {index > 0 && <div className="condition-set-separator">OR</div>}
                <div className="mb-4 border rounded p-4 bg-bg-light">
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
                                    noPadding
                                    onClick={() => duplicateConditionSet(index)}
                                />
                                {!isEarlyAccessFeatureCondition(group) && filterGroups.length > 1 && (
                                    <LemonButton
                                        icon={<IconTrash />}
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
                                <div className="feature-flag-property-display" key={idx}>
                                    {idx === 0 ? (
                                        <LemonButton
                                            icon={<IconSubArrowRight className="arrow-right" />}
                                            size="small"
                                        />
                                    ) : (
                                        <LemonButton icon={<span className="text-sm">&</span>} size="small" />
                                    )}
                                    <span className="simple-tag tag-light-blue text-primary-alt">
                                        {property.type === 'cohort' ? 'Cohort' : property.key}{' '}
                                    </span>
                                    {isPropertyFilterWithOperator(property) ? (
                                        <span>{allOperatorsToHumanName(property.operator)} </span>
                                    ) : null}

                                    {property.type === 'cohort' ? (
                                        <LemonButton
                                            type="secondary"
                                            size="xsmall"
                                            to={urls.cohort(property.value)}
                                            sideIcon={<IconOpenInNew />}
                                            targetBlank
                                        >
                                            {(property.value && cohortsById[property.value]?.name) ||
                                                `ID ${property.value}`}
                                        </LemonButton>
                                    ) : (
                                        [...(Array.isArray(property.value) ? property.value : [property.value])].map(
                                            (val, idx) => (
                                                <span
                                                    key={idx}
                                                    className="simple-tag tag-light-blue text-primary-alt display-value"
                                                >
                                                    {val}
                                                    {isPropertyFilterWithOperator(property) &&
                                                    ['is_date_before', 'is_date_after'].includes(property.operator) &&
                                                    dateStringToComponents(String(val)) // check it's a relative date
                                                        ? ` ( ${dateFilterToText(
                                                              String(val),
                                                              undefined,
                                                              '',
                                                              [],
                                                              false,
                                                              String(val).slice(-1) === 'h'
                                                                  ? 'MMMM D, YYYY HH:mm:ss'
                                                                  : 'MMMM D, YYYY',
                                                              true
                                                          )} )`
                                                        : ''}
                                                </span>
                                            )
                                        )
                                    )}
                                </div>
                            ))}
                        </>
                    ) : (
                        <div>
                            <PropertyFilters
                                orFiltering={true}
                                pageKey={`feature-flag-${id}-${index}-${filterGroups.length}-${
                                    filters.aggregation_group_type_index ?? ''
                                }`}
                                propertyFilters={group?.properties}
                                logicalRowDivider
                                addText="Add condition"
                                onChange={(properties) => updateConditionSet(index, undefined, properties)}
                                taxonomicGroupTypes={taxonomicGroupTypes}
                                taxonomicFilterOptionsFromProp={filtersTaxonomicOptions}
                                hasRowOperator={false}
                                sendAllKeyUpdates
                                allowRelativeDateOptions={!!enabledFeatures[FEATURE_FLAGS.NEW_FEATURE_FLAG_OPERATORS]}
                                errorMessages={
                                    propertySelectErrors?.[index]?.properties?.some((message) => !!message.value)
                                        ? propertySelectErrors[index].properties?.map((message, index) => {
                                              return message.value ? (
                                                  <div
                                                      key={index}
                                                      className="text-danger flex items-center gap-1 text-sm Field--error"
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
                                <LemonField.Pure error={propertySelectErrors?.[index]?.rollout_percentage}>
                                    <LemonInput
                                        data-attr="rollout-percentage"
                                        type="number"
                                        className="ml-2 mr-1.5 max-w-30"
                                        onChange={(value): void => {
                                            updateConditionSet(index, value === undefined ? 0 : value)
                                        }}
                                        value={group.rollout_percentage !== null ? group.rollout_percentage : 100}
                                        min={0}
                                        max={100}
                                        step="any"
                                        suffix={<span>%</span>}
                                    />
                                </LemonField.Pure>{' '}
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
        const hasMatchingEarlyAccessFeature = earlyAccessFeaturesList?.find((f: any) => f.flagKey === featureFlagKey)

        return (
            <div className="w-full" key={`${index}-${filterGroups.length}`}>
                {index > 0 && <div className="condition-set-separator">OR</div>}
                <div className="mb-4 rounded p-4 bg-bg-light">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center">
                            <div>
                                {group.properties?.length ? (
                                    <>
                                        Match <b>{aggregationTargetName}</b> against value set on{' '}
                                        <span className="simple-tag tag-light-blue text-primary-alt">
                                            {'$feature_enrollment/' + featureFlagKey}
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
                                <LemonButton icon={<IconSubArrowRight className="arrow-right" />} size="small" />
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
                            data-attr="feature-flag-feature-list-button"
                            size="small"
                            onClick={() =>
                                hasEarlyAccessFeatures &&
                                router.actions.push(urls.earlyAccessFeature(earlyAccessFeaturesList[0].id))
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
                {!readOnly && showGroupsOptions && !hideMatchOptions && (
                    <div className="centered">
                        Match by
                        <LemonSelect
                            dropdownMatchSelectWidth={false}
                            className="ml-2"
                            data-attr="feature-flag-aggregation-filter"
                            onChange={(value) => {
                                // MatchByGroupsIntroductionOption
                                if (value == -2) {
                                    return
                                }

                                const groupTypeIndex = value !== -1 ? value : null
                                setAggregationGroupTypeIndex(groupTypeIndex)
                            }}
                            value={
                                filters.aggregation_group_type_index != null ? filters.aggregation_group_type_index : -1
                            }
                            options={[
                                { value: -1, label: 'Users' },
                                ...Array.from(groupTypes.values()).map((groupType) => ({
                                    value: groupType.group_type_index,
                                    label: capitalizeFirstLetter(aggregationLabel(groupType.group_type_index).plural),
                                    disabledReason:
                                        // TODO: The first part of old condition seemed a bit wonky check if we do need it
                                        hasEarlyAccessFeatures
                                            ? 'This feature flag cannot be group-based, because it is linked to an early access feature.'
                                            : null,
                                })),
                                ...(includeGroupsIntroductionOption()
                                    ? [
                                          {
                                              value: -2,
                                              label: 'MatchByGroupsIntroductionOption',
                                              labelInMenu: matchByGroupsIntroductionOption,
                                          },
                                      ]
                                    : []),
                            ]}
                        />
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
