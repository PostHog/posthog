import { useValues } from 'kea'

import { IconFlag } from '@posthog/icons'
import { LemonButton, LemonLabel, LemonSnack, LemonTag } from '@posthog/lemon-ui'

import { allOperatorsToHumanName } from 'lib/components/DefinitionPopover/utils'
import { isPropertyFilterWithOperator } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { IconOpenInNew, IconSubArrowRight } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { getFilterLabel } from '~/taxonomy/helpers'
import {
    AnyPropertyFilter,
    FeatureFlagEvaluationRuntime,
    FeatureFlagFilters,
    FeatureFlagGroupType,
    PropertyFilterType,
} from '~/types'

import { EarlyExitIndicator } from './EarlyExitIndicator'
import { FeatureFlagConditionWarning } from './FeatureFlagConditionWarning'
import { featureFlagReleaseConditionsLogic, isDistinctIdFilter } from './featureFlagReleaseConditionsLogic'

interface FeatureFlagReleaseConditionsReadonlyProps {
    id: string
    filters: FeatureFlagFilters
    isDisabled?: boolean
    evaluationRuntime?: FeatureFlagEvaluationRuntime
}

/** Extract server-provided group_key_names from a property, if present. */
function getGroupKeyNames(property: AnyPropertyFilter): Record<string, string> {
    if (property.type === PropertyFilterType.Group && 'group_key_names' in property) {
        return (property as any).group_key_names ?? {}
    }
    return {}
}

function PropertyValueDisplay({
    property,
    getDistinctIdName,
}: {
    property: AnyPropertyFilter
    getDistinctIdName: (distinctId: string) => string
}): JSX.Element {
    if (property.type === PropertyFilterType.Cohort) {
        return (
            <LemonButton type="secondary" size="xsmall" to={urls.cohort(property.value)} sideIcon={<IconOpenInNew />}>
                {property.cohort_name || `ID ${property.value}`}
            </LemonButton>
        )
    }

    const propertyValues = Array.isArray(property.value) ? property.value : [property.value]
    const groupKeyNames = property.key === '$group_key' ? getGroupKeyNames(property) : {}
    const isDistinctId = isDistinctIdFilter(property)

    return (
        <>
            {propertyValues.map((val, idx) => {
                const strVal = String(val)
                const display = isDistinctId ? getDistinctIdName(strVal) : groupKeyNames[strVal] || strVal
                return <LemonSnack key={idx}>{display}</LemonSnack>
            })}
        </>
    )
}

function PropertyFilterRow({
    property,
    isFirst,
    getDistinctIdName,
}: {
    property: AnyPropertyFilter
    isFirst: boolean
    getDistinctIdName: (distinctId: string) => string
}): JSX.Element {
    const propertyLabel =
        property.type === PropertyFilterType.Cohort || property.type === PropertyFilterType.Flag
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
            {propertyLabel && propertyLabel !== property.key && <span className="text-muted">{propertyLabel}</span>}
            {property.type === PropertyFilterType.Flag ? (
                <LemonSnack>
                    <IconFlag className="mr-1" />
                    {property.label || property.key}
                </LemonSnack>
            ) : (
                <LemonSnack>{property.type === PropertyFilterType.Cohort ? 'Cohort' : property.key}</LemonSnack>
            )}
            <span className="text-muted">{operator}</span>
            <PropertyValueDisplay property={property} getDistinctIdName={getDistinctIdName} />
        </div>
    )
}

export function FeatureFlagReleaseConditionsReadonly({
    id,
    filters,
    isDisabled,
    evaluationRuntime,
}: FeatureFlagReleaseConditionsReadonlyProps): JSX.Element {
    // Use readOnly: true to prevent the logic from triggering blast radius API calls.
    // In readonly mode, we don't need live blast radius calculations - the display is static.
    const releaseConditionsLogic = featureFlagReleaseConditionsLogic({
        id,
        readOnly: true,
        filters,
    })

    const { filterGroups, aggregationTargetName, properties, getDistinctIdName } = useValues(releaseConditionsLogic)

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

            {filters.early_exit && <EarlyExitIndicator />}

            <FeatureFlagConditionWarning properties={properties} evaluationRuntime={evaluationRuntime} />

            <div className={isDisabled ? 'opacity-60' : ''}>
                {filterGroups.map((group, index) => (
                    <div key={group.sort_key ?? index}>
                        {index > 0 && (
                            <div className="condition-set-separator my-2 py-0 text-center text-xs font-semibold text-muted">
                                OR
                            </div>
                        )}
                        <ConditionSetCard
                            group={group}
                            index={index}
                            aggregationTargetName={aggregationTargetName(group.aggregation_group_type_index)}
                            getDistinctIdName={getDistinctIdName}
                        />
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
    getDistinctIdName: (distinctId: string) => string
}

function ConditionSetCard({
    group,
    index,
    aggregationTargetName,
    getDistinctIdName,
}: ConditionSetCardProps): JSX.Element {
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
                        <PropertyFilterRow
                            key={idx}
                            property={property}
                            isFirst={idx === 0}
                            getDistinctIdName={getDistinctIdName}
                        />
                    ))}
                </div>
            )}

            <div className="mt-3">
                <LemonTag type={rollout === 100 ? 'highlight' : rollout === 0 ? 'caution' : 'none'}>
                    <span className="text-sm">
                        Rolled out to <b className="tabular-nums">{rollout}%</b> of <b>{aggregationTargetName}</b> in
                        this set.
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
