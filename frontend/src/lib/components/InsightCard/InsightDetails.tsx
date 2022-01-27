import { useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { allOperatorsMapping, alphabet } from 'lib/utils'
import React from 'react'
import { LocalFilter, toLocalFilters } from 'scenes/insights/ActionFilter/entityFilterLogic'
import { BreakdownFilter } from 'scenes/insights/BreakdownFilter'
import { mathsLogic } from 'scenes/trends/mathsLogic'
import { urls } from 'scenes/urls'
import { InsightModel, InsightType, PropertyFilter } from '~/types'
import { IconCalculate, IconSubdirectoryArrowRight } from '../icons'
import { LemonRow, LemonSpacer } from '../LemonRow'
import { Lettermark } from '../Lettermark/Lettermark'
import { Link } from '../Link'
import { ProfilePicture } from '../ProfilePicture'
import { PropertyFilterText } from '../PropertyFilters/components/PropertyFilterButton'
import { PropertyKeyInfo } from '../PropertyKeyInfo'
import { TZLabel } from '../TimezoneAware'

function CompactPropertyFiltersDisplay({
    properties,
    embedded,
}: {
    properties: PropertyFilter[]
    embedded?: boolean
}): JSX.Element {
    return (
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
                                    <PropertyKeyInfo value={subFilter.key} />
                                </span>
                                {allOperatorsMapping[subFilter.operator || 'exact']} <b>{subFilter.value}</b>
                            </>
                        )}
                    </span>
                </div>
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
                            <b>
                                {mathDefinitions[
                                    insightType === InsightType.LIFECYCLE ? 'dau' : filter.math || 'total'
                                ].name.toLowerCase()}
                            </b>
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

function InsightDetailsInternal({ insight }: { insight: InsightModel }, ref: React.Ref<HTMLDivElement>): JSX.Element {
    const { filters, created_at, created_by } = insight

    const { featureFlags } = useValues(featureFlagLogic)

    const localFilters = toLocalFilters(filters)

    return (
        <div className="InsightDetails" ref={ref}>
            <h5>Query summary</h5>
            <section className="InsightDetails__query">
                {filters.formula && (
                    <>
                        <LemonRow className="InsightDetails__formula" icon={<IconCalculate />} fullWidth>
                            <span>
                                Formula:<code>{filters.formula}</code>
                            </span>
                        </LemonRow>
                        <LemonSpacer />
                    </>
                )}
                <div className="InsightDetails__series">
                    <SeriesDisplay filter={localFilters[0]} insightType={filters.insight} index={0} />
                    {localFilters.slice(1).map((filter, index) => (
                        <>
                            <LemonSpacer />
                            <SeriesDisplay
                                key={index}
                                filter={filter}
                                insightType={filters.insight}
                                index={index + 1}
                            />
                        </>
                    ))}
                </div>
            </section>
            <h5>Filters</h5>
            <section>
                {filters.properties?.length ? (
                    <CompactPropertyFiltersDisplay properties={filters.properties} />
                ) : (
                    <i>None</i>
                )}
            </section>
            <div className="InsightDetails__footer">
                <div>
                    <h5>Created by</h5>
                    <section>
                        <ProfilePicture name={created_by?.first_name} email={created_by?.email} showName size="md" />{' '}
                        <TZLabel time={created_at} />
                    </section>
                </div>
                {filters.breakdown_type && (
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
                )}
            </div>
        </div>
    )
}
export const InsightDetails = React.memo(React.forwardRef(InsightDetailsInternal))
