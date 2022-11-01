import { useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { allOperatorsMapping, alphabet, capitalizeFirstLetter, formatPropertyLabel } from 'lib/utils'
import { LocalFilter, toLocalFilters } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'
import { BreakdownFilter } from 'scenes/insights/filters/BreakdownFilter'
import { humanizePathsEventTypes } from 'scenes/insights/utils'
import { apiValueToMathType, MathCategory, MathDefinition, mathsLogic } from 'scenes/trends/mathsLogic'
import { urls } from 'scenes/urls'
import { FilterLogicalOperator, FilterType, InsightModel, InsightType, PropertyGroupFilter } from '~/types'
import { IconCalculate, IconSubdirectoryArrowRight } from '../../icons'
import { LemonRow } from '../../LemonRow'
import { LemonDivider } from '../../LemonDivider'
import { Lettermark } from '../../Lettermark/Lettermark'
import { Link } from '../../Link'
import { ProfilePicture } from '../../ProfilePicture'
import { keyMapping, PropertyKeyInfo } from '../../PropertyKeyInfo'
import { TZLabel } from '../../TimezoneAware'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { cohortsModel } from '~/models/cohortsModel'
import React from 'react'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'

function CompactPropertyFiltersDisplay({
    groupFilter,
    embedded,
}: {
    groupFilter: PropertyGroupFilter | null
    embedded?: boolean
}): JSX.Element {
    const { cohortsById } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

    const areAnyFiltersPresent = !!groupFilter && groupFilter.values.flatMap((subValues) => subValues.values).length > 0

    if (!areAnyFiltersPresent) {
        return <i>None</i>
    }

    return (
        <>
            {groupFilter.values.map(({ values: subValues, type: subType }, subIndex) => (
                <React.Fragment key={subIndex}>
                    {subIndex === 0 ? null : groupFilter.type === FilterLogicalOperator.Or ? 'OR' : 'AND'}
                    {subValues.map((leafFilter, leafIndex) => {
                        const isFirstFilterWithinSubgroup = leafIndex === 0
                        const isFirstFilterOverall = isFirstFilterWithinSubgroup && subIndex === 0

                        return (
                            <div key={leafIndex} className="SeriesDisplay__condition">
                                {embedded && <IconSubdirectoryArrowRight className="SeriesDisplay__arrow" />}
                                <span>
                                    {isFirstFilterWithinSubgroup
                                        ? embedded
                                            ? 'where '
                                            : null
                                        : subType === FilterLogicalOperator.Or
                                        ? 'or '
                                        : 'and '}
                                    {leafFilter.type === 'cohort' ? (
                                        <>
                                            {isFirstFilterOverall && !embedded ? 'Person' : 'person'} belongs to cohort
                                            <span className="SeriesDisplay__raw-name">
                                                {formatPropertyLabel(
                                                    leafFilter,
                                                    cohortsById,
                                                    keyMapping,
                                                    (s) =>
                                                        formatPropertyValueForDisplay(leafFilter.key, s)?.toString() ||
                                                        '?'
                                                )}
                                            </span>
                                        </>
                                    ) : (
                                        <>
                                            {isFirstFilterOverall && !embedded
                                                ? capitalizeFirstLetter(leafFilter.type || 'event')
                                                : leafFilter.type || 'event'}
                                            's
                                            <span className="SeriesDisplay__raw-name">
                                                {leafFilter.key && <PropertyKeyInfo value={leafFilter.key} />}
                                            </span>
                                            {allOperatorsMapping[leafFilter.operator || 'exact']}{' '}
                                            <b>
                                                {Array.isArray(leafFilter.value)
                                                    ? leafFilter.value.join(' or ')
                                                    : leafFilter.value}
                                            </b>
                                        </>
                                    )}
                                </span>
                            </div>
                        )
                    })}
                </React.Fragment>
            ))}
        </>
    )
}

function SeriesDisplay({
    filter,
    insightType = InsightType.TRENDS,
    index,
}: {
    filter: LocalFilter
    insightType?: InsightType
    index: number
}): JSX.Element {
    const { mathDefinitions } = useValues(mathsLogic)

    const mathDefinition = mathDefinitions[
        insightType === InsightType.LIFECYCLE
            ? 'dau'
            : filter.math
            ? apiValueToMathType(filter.math, filter.math_group_type_index)
            : 'total'
    ] as MathDefinition | undefined

    return (
        <LemonRow
            fullWidth
            className="SeriesDisplay"
            icon={<Lettermark name={insightType !== InsightType.FUNNELS ? alphabet[index] : index + 1} />}
            extendedContent={
                <>
                    {insightType !== InsightType.FUNNELS && (
                        <div>
                            counted by{' '}
                            {mathDefinition?.category === MathCategory.PropertyValue && filter.math_property && (
                                <>
                                    {' '}
                                    event's
                                    <span className="SeriesDisplay__raw-name">
                                        <PropertyKeyInfo value={filter.math_property} />
                                    </span>
                                </>
                            )}
                            <b>{mathDefinition?.name.toLowerCase()}</b>
                        </div>
                    )}
                    {filter.properties && filter.properties.length > 0 && (
                        <CompactPropertyFiltersDisplay
                            groupFilter={{
                                type: FilterLogicalOperator.And,
                                values: [{ type: FilterLogicalOperator.And, values: filter.properties }],
                            }}
                            embedded
                        />
                    )}
                </>
            }
        >
            <span>
                {insightType === InsightType.FUNNELS ? 'Performed' : 'Showing'}
                {filter.custom_name && <b> "{filter.custom_name}"</b>}
                {filter.type === 'actions' && filter.id ? (
                    <Link
                        to={urls.action(filter.id)}
                        className="SeriesDisplay__raw-name SeriesDisplay__raw-name--action"
                        title="Action series"
                    >
                        {filter.name}
                    </Link>
                ) : (
                    <span className="SeriesDisplay__raw-name SeriesDisplay__raw-name--event" title="Event series">
                        <PropertyKeyInfo value={filter.name || '$pageview'} />
                    </span>
                )}
            </span>
        </LemonRow>
    )
}

function PathsSummary({ filters }: { filters: Partial<FilterType> }): JSX.Element {
    // Sync format with summarizePaths in utils
    return (
        <div className="SeriesDisplay">
            <div>
                User paths based on <b>{humanizePathsEventTypes(filters).join(' and ')}</b>
            </div>
            {filters.start_point && (
                <div>
                    starting at <b>{filters.start_point}</b>
                </div>
            )}
            {filters.end_point && (
                <div>
                    ending at <b>{filters.end_point}</b>
                </div>
            )}
        </div>
    )
}

export function QuerySummary({ filters }: { filters: Partial<FilterType> }): JSX.Element {
    const localFilters = toLocalFilters(filters)

    return (
        <>
            <h5>Query summary</h5>
            <section className="InsightDetails__query">
                {filters.formula && (
                    <>
                        <LemonRow className="InsightDetails__formula" icon={<IconCalculate />} fullWidth>
                            <span>
                                Formula:<code>{filters.formula}</code>
                            </span>
                        </LemonRow>
                        <LemonDivider />
                    </>
                )}
                <div className="InsightDetails__series">
                    {filters.insight === InsightType.PATHS ? (
                        <PathsSummary filters={filters} />
                    ) : (
                        <>
                            {localFilters.length > 0 && (
                                <>
                                    <SeriesDisplay filter={localFilters[0]} insightType={filters.insight} index={0} />
                                    {localFilters.slice(1).map((filter, index) => (
                                        <>
                                            <LemonDivider />
                                            <SeriesDisplay
                                                key={index}
                                                filter={filter}
                                                insightType={filters.insight}
                                                index={index + 1}
                                            />
                                        </>
                                    ))}
                                </>
                            )}
                        </>
                    )}
                </div>
            </section>
        </>
    )
}

export function FiltersSummary({ filters }: { filters: Partial<FilterType> }): JSX.Element {
    const groupFilter: PropertyGroupFilter | null = Array.isArray(filters.properties)
        ? {
              type: FilterLogicalOperator.And,
              values: [
                  {
                      type: FilterLogicalOperator.And,
                      values: filters.properties,
                  },
              ],
          }
        : filters.properties || null

    return (
        <>
            <h5>Filters</h5>
            <section>
                <CompactPropertyFiltersDisplay groupFilter={groupFilter} />
            </section>
        </>
    )
}

export function BreakdownSummary({ filters }: { filters: Partial<FilterType> }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    return (
        <div>
            <h5>Breakdown by</h5>
            <BreakdownFilter
                filters={filters}
                useMultiBreakdown={
                    filters.insight === InsightType.FUNNELS &&
                    !!featureFlags[FEATURE_FLAGS.BREAKDOWN_BY_MULTIPLE_PROPERTIES]
                }
            />
        </div>
    )
}

function InsightDetailsInternal(
    { insight, onDashboard }: { insight: InsightModel; onDashboard: boolean },
    ref: React.Ref<HTMLDivElement>
): JSX.Element {
    const { filters, created_at, created_by, description, tags } = insight
    const { featureFlags } = useValues(featureFlagLogic)
    const minimalistMode: boolean = !!featureFlags[FEATURE_FLAGS.MINIMALIST_MODE]

    return (
        <div className="InsightDetails" ref={ref}>
            {onDashboard && minimalistMode && (
                <>
                    <div className="InsightMeta__description">{description || <i>No description</i>}</div>
                    <UserActivityIndicator at={insight.last_modified_at} by={insight.last_modified_by} />
                    {tags && tags.length > 0 && <ObjectTags tags={tags} staticOnly className={'my-1'} />}
                    <LemonDivider />
                </>
            )}
            <QuerySummary filters={filters} />
            <FiltersSummary filters={filters} />
            <div className="InsightDetails__footer">
                <div>
                    <h5>Created by</h5>
                    <section>
                        <ProfilePicture name={created_by?.first_name} email={created_by?.email} showName size="md" />{' '}
                        <TZLabel time={created_at} />
                    </section>
                </div>
                {filters.breakdown_type && <BreakdownSummary filters={filters} />}
            </div>
        </div>
    )
}
export const InsightDetails = React.memo(React.forwardRef(InsightDetailsInternal))
