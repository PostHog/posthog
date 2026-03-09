import { useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonLabel, LemonSnack, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { allOperatorsToHumanName } from 'lib/components/DefinitionPopover/utils'
import { isPropertyFilterWithOperator } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { IconOpenInNew, IconSubArrowRight } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { getFilterLabel } from '~/taxonomy/helpers'
import { AnyPropertyFilter, FeatureFlagFilters, FeatureFlagGroupType, PropertyFilterType } from '~/types'

import { featureFlagReleaseConditionsLogic } from './featureFlagReleaseConditionsLogic'

interface FeatureFlagReleaseConditionsReadonlyProps {
    id: string
    filters: FeatureFlagFilters
    isDisabled?: boolean
}

function PropertyValueDisplay({ property }: { property: AnyPropertyFilter }): JSX.Element {
    if (property.type === PropertyFilterType.Cohort) {
        return (
            <LemonButton type="secondary" size="xsmall" to={urls.cohort(property.value)} sideIcon={<IconOpenInNew />}>
                {property.cohort_name || `ID ${property.value}`}
            </LemonButton>
        )
    }

    const propertyValues = Array.isArray(property.value) ? property.value : [property.value]

    return (
        <>
            {propertyValues.map((val, idx) => (
                <LemonSnack key={idx}>{String(val)}</LemonSnack>
            ))}
        </>
    )
}

function PropertyFilterRow({ property, isFirst }: { property: AnyPropertyFilter; isFirst: boolean }): JSX.Element {
    const propertyLabel =
        property.type === PropertyFilterType.Cohort
            ? null
            : getFilterLabel(
                  property.key,
                  property.type === PropertyFilterType.Person
                      ? TaxonomicFilterGroupType.PersonProperties
                      : TaxonomicFilterGroupType.EventProperties
              )

    const operator = isPropertyFilterWithOperator(property) ? allOperatorsToHumanName(property.operator) : 'equals'

    return (
        <div className="flex items-center gap-1.5 flex-wrap text-sm">
            {isFirst ? (
                <LemonButton icon={<IconSubArrowRight className="arrow-right" />} size="small" noPadding />
            ) : (
                <LemonButton icon={<span className="text-xs font-medium">&</span>} size="small" noPadding />
            )}
            {propertyLabel && <span className="text-muted">{propertyLabel}</span>}
            <LemonSnack>{property.type === PropertyFilterType.Cohort ? 'Cohort' : property.key}</LemonSnack>
            <span className="text-muted">{operator}</span>
            <PropertyValueDisplay property={property} />
        </div>
    )
}

export function FeatureFlagReleaseConditionsReadonly({
    id,
    filters,
    isDisabled,
}: FeatureFlagReleaseConditionsReadonlyProps): JSX.Element {
    // Use readOnly: true to prevent the logic from triggering blast radius API calls.
    // In readonly mode, we don't need live blast radius calculations - the display is static.
    const releaseConditionsLogic = featureFlagReleaseConditionsLogic({
        id,
        readOnly: true,
        filters,
    })

    const { filterGroups, aggregationTargetName } = useValues(releaseConditionsLogic)

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
                <LemonLabel>Release conditions</LemonLabel>
                {isDisabled && (
                    <LemonTag type="muted" size="small">
                        Flag disabled – returns false regardless of conditions
                    </LemonTag>
                )}
            </div>

            <p className="text-xs text-muted mb-2">
                Condition sets are evaluated top to bottom — the first match wins.
            </p>

            <div className={isDisabled ? 'opacity-60' : ''}>
                {filterGroups.map((group, index) => (
                    <div key={group.sort_key ?? index}>
                        {index > 0 && (
                            <div className="condition-set-separator my-2 py-0 text-center text-xs font-semibold text-muted">
                                OR
                            </div>
                        )}
                        <ConditionSetCard group={group} index={index} aggregationTargetName={aggregationTargetName} />
                    </div>
                ))}

                {filterGroups.length === 0 && (
                    <div className="text-sm text-muted">No release conditions configured</div>
                )}
            </div>
        </div>
    )
}

interface ConditionSetCardProps {
    group: FeatureFlagGroupType
    index: number
    aggregationTargetName: string
}

function ConditionSetCard({ group, index, aggregationTargetName }: ConditionSetCardProps): JSX.Element {
    const properties = group.properties || []
    const rollout = group.rollout_percentage ?? 100

    const getSummary = (): JSX.Element => {
        if (properties.length === 0) {
            return (
                <>
                    Condition set will match <b>all {aggregationTargetName}</b>
                </>
            )
        }
        return (
            <>
                Match <b>{aggregationTargetName}</b> against <b>all</b> criteria
            </>
        )
    }

    return (
        <div className="border rounded p-4 bg-surface-primary">
            <div className="flex items-center gap-2 flex-wrap">
                <LemonSnack>Set {index + 1}</LemonSnack>
                <span className="text-sm">{getSummary()}</span>
            </div>

            {group.description && <div className="mt-2 text-sm text-muted">{group.description}</div>}

            {properties.length > 0 && (
                <div className="mt-3 flex flex-col gap-1">
                    {properties.map((property, idx) => (
                        <PropertyFilterRow key={idx} property={property} isFirst={idx === 0} />
                    ))}
                </div>
            )}

            <div className="mt-3">
                <LemonTag type={rollout === 100 ? 'highlight' : rollout === 0 ? 'caution' : 'none'}>
                    <span className="text-sm">
                        Rolled out to <b>{rollout}%</b> of <b>{aggregationTargetName}</b> in this set.
                    </span>
                </LemonTag>
            </div>

            {group.variant && (
                <div className="mt-3 text-sm">
                    All <b>{aggregationTargetName}</b> in this set will be in variant <b>{group.variant}</b>
                </div>
            )}
        </div>
    )
}

// Minimal type for early access features as they appear on featureFlag.features
// The actual API response shape differs from the formal EarlyAccessFeatureType
interface EarlyAccessFeatureSummary {
    id: string
    flagKey: string
}

interface FeatureFlagSuperConditionsReadonlyProps {
    id: string
    flagKey: string
    filters: FeatureFlagFilters
    earlyAccessFeatures?: EarlyAccessFeatureSummary[]
    isDisabled?: boolean
}

export function FeatureFlagSuperConditionsReadonly({
    id,
    flagKey,
    filters,
    earlyAccessFeatures,
    isDisabled,
}: FeatureFlagSuperConditionsReadonlyProps): JSX.Element | null {
    const releaseConditionsLogic = featureFlagReleaseConditionsLogic({
        id,
        readOnly: true,
        isSuper: true,
        filters,
    })

    const { filterGroups, aggregationTargetName } = useValues(releaseConditionsLogic)
    const matchingEarlyAccessFeature = earlyAccessFeatures?.find((f) => f.flagKey === flagKey)

    if (filterGroups.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
                <LemonLabel className="flex items-center gap-1">
                    Super release conditions
                    <Tooltip title="This flag is linked to an early access feature. Super conditions are managed through the early access feature and take priority over regular release conditions.">
                        <IconInfo className="text-muted text-base" />
                    </Tooltip>
                </LemonLabel>
                {isDisabled && (
                    <LemonTag type="muted" size="small">
                        Flag disabled – returns false regardless of conditions
                    </LemonTag>
                )}
            </div>

            <div className={isDisabled ? 'opacity-60' : ''}>
                {filterGroups.map((group, index) => (
                    <div key={group.sort_key ?? index}>
                        {index > 0 && (
                            <div className="condition-set-separator my-2 py-0 text-center text-xs font-semibold text-muted">
                                OR
                            </div>
                        )}
                        <div className="border rounded p-4 bg-surface-primary">
                            <div className="text-sm">
                                {group.properties?.length ? (
                                    <>
                                        Match <b>{aggregationTargetName}</b> against value set on{' '}
                                        <LemonSnack>{'$feature_enrollment/' + flagKey}</LemonSnack>
                                    </>
                                ) : (
                                    <>
                                        Condition set will match <b>all {aggregationTargetName}</b>
                                    </>
                                )}
                            </div>

                            {(group.properties?.length || 0) > 0 && (
                                <>
                                    <LemonDivider className="my-3" />
                                    <div className="flex items-center gap-1.5 text-sm">
                                        <LemonButton
                                            icon={<IconSubArrowRight className="arrow-right" />}
                                            size="small"
                                            noPadding
                                        />
                                        <span>
                                            If null, default to <b>Release conditions</b>
                                        </span>
                                    </div>
                                </>
                            )}

                            <LemonDivider className="my-3" />

                            <div className="flex justify-end">
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    to={
                                        matchingEarlyAccessFeature
                                            ? urls.earlyAccessFeature(matchingEarlyAccessFeature.id)
                                            : undefined
                                    }
                                    disabledReason={
                                        !matchingEarlyAccessFeature
                                            ? 'The matching early access feature was not found'
                                            : undefined
                                    }
                                    sideIcon={matchingEarlyAccessFeature ? <IconOpenInNew /> : undefined}
                                >
                                    View Early Access Feature
                                </LemonButton>
                            </div>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    )
}
