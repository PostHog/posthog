import { useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { allOperatorsMapping, alphabet, isPropertyGroup } from 'lib/utils'
import React from 'react'
import { LocalFilter, toLocalFilters } from 'scenes/insights/ActionFilter/entityFilterLogic'
import { BreakdownFilter } from 'scenes/insights/BreakdownFilter'
import { humanizePathsEventTypes } from 'scenes/insights/utils'
import { apiValueToMathType, MathDefinition, mathsLogic } from 'scenes/trends/mathsLogic'
import { urls } from 'scenes/urls'
import {
    FilterLogicalOperator,
    FilterType,
    InsightModel,
    InsightType,
    PropertyFilter,
    PropertyGroupFilter,
} from '~/types'
import { IconCalculate, IconSubdirectoryArrowRight } from '../icons'
import { LemonRow } from '../LemonRow'
import { LemonDivider } from '../LemonDivider'
import { Lettermark } from '../Lettermark/Lettermark'
import { Link } from '../Link'
import { ProfilePicture } from '../ProfilePicture'
import { PropertyFilterText } from '../PropertyFilters/components/PropertyFilterButton'
import { PropertyKeyInfo } from '../PropertyKeyInfo'
import { TZLabel } from '../TimezoneAware'
import { DefinitionPopup } from '../DefinitionPopup/DefinitionPopup'

function CompactPropertyFiltersDisplay({
    properties,
    embedded,
}: {
    properties: PropertyFilter[] | PropertyGroupFilter
    embedded?: boolean
}): JSX.Element {
    return (
        <>
            {isPropertyGroup(properties) ? (
                <>
                    {properties.values.map((propertyGroup, idx) => (
                        <>
                            <DefinitionPopup.Section>
                                <DefinitionPopup.Card
                                    title={
                                        <span className="card-secondary">
                                            Match against{' '}
                                            {propertyGroup.type === FilterLogicalOperator.Or ? 'any' : 'all'} criteria
                                        </span>
                                    }
                                    value={
                                        <ul>
                                            {propertyGroup.values.slice(0).map((subFilter, subIndex) => (
                                                <li key={subIndex}>
                                                    {subFilter.type === 'cohort' ? (
                                                        <>
                                                            person belongs to cohort
                                                            <span className="SeriesDisplay__raw-name">
                                                                <PropertyFilterText item={subFilter} />
                                                            </span>
                                                        </>
                                                    ) : (
                                                        <>
                                                            {subFilter.type || 'event'}'s
                                                            <span className="SeriesDisplay__raw-name">
                                                                {subFilter.key && (
                                                                    <PropertyKeyInfo value={subFilter.key} />
                                                                )}
                                                            </span>
                                                            {allOperatorsMapping[subFilter.operator || 'exact']}{' '}
                                                            <b>{subFilter.value}</b>
                                                        </>
                                                    )}
                                                </li>
                                            ))}
                                        </ul>
                                    }
                                />
                            </DefinitionPopup.Section>
                            {idx < Math.min(properties.values.length, 2) - 1 && (
                                <DefinitionPopup.HorizontalLine
                                    style={{ marginTop: 4, marginBottom: 12, fontSize: 11 }}
                                >
                                    {properties.type}
                                </DefinitionPopup.HorizontalLine>
                            )}
                        </>
                    ))}
                </>
            ) : (
                <>
                    {properties.map((subFilter, subIndex) => (
                        <div key={subIndex} className="SeriesDisplay__condition">
                            {embedded && <IconSubdirectoryArrowRight className="SeriesDisplay__arrow" />}
                            <span>
                                {subIndex === 0 ? (embedded ? 'where ' : 'Where ') : 'and '}
                                {subFilter.type === 'cohort' ? (
                                    <>
                                        person belongs to cohort
                                        <span className="SeriesDisplay__raw-name">
                                            <PropertyFilterText item={subFilter} />
                                        </span>
                                    </>
                                ) : (
                                    <>
                                        {subFilter.type || 'event'}'s
                                        <span className="SeriesDisplay__raw-name">
                                            {subFilter.key && <PropertyKeyInfo value={subFilter.key} />}
                                        </span>
                                        {allOperatorsMapping[subFilter.operator || 'exact']} <b>{subFilter.value}</b>
                                    </>
                                )}
                            </span>
                        </div>
                    ))}
                </>
            )}
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
                            {mathDefinition?.onProperty && filter.math_property && (
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
                        <CompactPropertyFiltersDisplay properties={filter.properties} embedded />
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
    return (
        <>
            <h5>Filters</h5>
            <section>
                {isPropertyGroup(filters.properties) && filters.properties.values.length ? (
                    <CompactPropertyFiltersDisplay properties={filters.properties} />
                ) : (
                    <i>None</i>
                )}
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

function InsightDetailsInternal({ insight }: { insight: InsightModel }, ref: React.Ref<HTMLDivElement>): JSX.Element {
    const { filters, created_at, created_by } = insight

    return (
        <div className="InsightDetails" ref={ref}>
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
