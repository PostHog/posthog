import { Query } from '~/queries/Query/Query'
import { useActions, useValues } from 'kea'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { isEventPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { DataTableNode, NodeKind, QuerySchema, WebStatsBreakdown } from '~/queries/schema'
import { QueryContext, QueryContextColumnComponent, QueryContextColumnTitleComponent } from '~/queries/types'
import { UnexpectedNeverError } from 'lib/utils'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { IconBugReport, IconFeedback, IconGithub } from 'lib/lemon-ui/icons'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { Link } from 'lib/lemon-ui/Link'
import { useCallback } from 'react'

const PercentageCell: QueryContextColumnComponent = ({ value }) => {
    if (typeof value === 'number') {
        return <span>{`${(value * 100).toFixed(1)}%`}</span>
    } else {
        return null
    }
}

const NumericCell: QueryContextColumnComponent = ({ value }) => {
    return <span>{typeof value === 'number' ? value.toLocaleString() : String(value)}</span>
}

const BreakdownValueTitle: QueryContextColumnTitleComponent = (props) => {
    const { query } = props
    const { source } = query
    if (source.kind !== NodeKind.WebStatsTableQuery) {
        return null
    }
    const { breakdownBy } = source
    switch (breakdownBy) {
        case WebStatsBreakdown.Page:
            return <>Path</>
        case WebStatsBreakdown.InitialPage:
            return <>Initial Path</>
        case WebStatsBreakdown.InitialReferringDomain:
            return <>Referring Domain</>
        case WebStatsBreakdown.InitialUTMSource:
            return <>UTM Source</>
        case WebStatsBreakdown.InitialUTMCampaign:
            return <>UTM Campaign</>
        case WebStatsBreakdown.Browser:
            return <>Browser</>
        case WebStatsBreakdown.OS:
            return <>OS</>
        case WebStatsBreakdown.DeviceType:
            return <>Device Type</>
        default:
            throw new UnexpectedNeverError(breakdownBy)
    }
}

const BreakdownValueCell: QueryContextColumnComponent = (props) => {
    const { value, query } = props
    const { source } = query
    if (source.kind !== NodeKind.WebStatsTableQuery) {
        return null
    }
    if (typeof value !== 'string') {
        return null
    }

    return <BreakdownValueCellInner value={value} />
}

const webStatsBreakdownToPropertyName = (breakdownBy: WebStatsBreakdown): string => {
    switch (breakdownBy) {
        case WebStatsBreakdown.Page:
            return '$pathname'
        case WebStatsBreakdown.InitialPage:
            return '$initial_pathname'
        case WebStatsBreakdown.InitialReferringDomain:
            return '$initial_referrer'
        case WebStatsBreakdown.InitialUTMSource:
            return '$initial_utm_source'
        case WebStatsBreakdown.InitialUTMCampaign:
            return '$initial_utm_campaign'
        case WebStatsBreakdown.Browser:
            return '$browser'
        case WebStatsBreakdown.OS:
            return '$os'
        case WebStatsBreakdown.DeviceType:
            return '$device_type'
        default:
            throw new UnexpectedNeverError(breakdownBy)
    }
}

const BreakdownValueCellInner = ({ value }: { value: string }): JSX.Element => {
    return <span>{value}</span>
}

const queryContext: QueryContext = {
    columns: {
        breakdown_value: {
            renderTitle: BreakdownValueTitle,
            render: BreakdownValueCell,
        },
        bounce_rate: {
            title: 'Bounce Rate',
            render: PercentageCell,
            align: 'right',
        },
        views: {
            title: 'Views',
            render: NumericCell,
            align: 'right',
        },
        visitors: {
            title: 'Visitors',
            render: NumericCell,
            align: 'right',
        },
    },
}

const Filters = (): JSX.Element => {
    const { webAnalyticsFilters, dateTo, dateFrom } = useValues(webAnalyticsLogic)
    const { setWebAnalyticsFilters, setDates } = useActions(webAnalyticsLogic)
    return (
        <div className="sticky top-0 bg-white z-20 pt-2">
            <div className="flex flex-row flex-wrap gap-2">
                <DateFilter dateFrom={dateFrom} dateTo={dateTo} onChange={setDates} />
                <PropertyFilters
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                    onChange={(filters) => setWebAnalyticsFilters(filters.filter(isEventPropertyFilter))}
                    propertyFilters={webAnalyticsFilters}
                    pageKey={'web-analytics'}
                />
            </div>
            <div className={'bg-border h-px w-full mt-2'} />
        </div>
    )
}

const Tiles = (): JSX.Element => {
    const { tiles } = useValues(webAnalyticsLogic)

    return (
        <div className="mt-2 grid grid-cols-1 md:grid-cols-12 gap-4">
            {tiles.map((tile, i) => {
                if ('query' in tile) {
                    const { query, title, layout } = tile
                    return (
                        <div
                            key={i}
                            className={`col-span-1 row-span-1 md:col-span-${layout.colSpan ?? 6} md:row-span-${
                                layout.rowSpan ?? 1
                            }  flex flex-col`}
                        >
                            {title && <h2 className="m-0  mb-1">{title}</h2>}
                            <QueryTile query={query} />
                        </div>
                    )
                } else if ('tabs' in tile) {
                    const { tabs, activeTabId, layout, setTabId } = tile
                    const tab = tabs.find((t) => t.id === activeTabId)
                    if (!tab) {
                        return null
                    }
                    const { query, title } = tab
                    return (
                        <div
                            key={i}
                            className={`col-span-1 row-span-1 md:col-span-${layout.colSpan ?? 6} md:row-span-${
                                layout.rowSpan ?? 1
                            } flex flex-col`}
                        >
                            <div className="flex flex-row items-center">
                                {<h2 className="flex-1 m-0 mb-1">{title}</h2>}
                                {tabs.length > 1 && (
                                    <div className="space-x-2">
                                        {/* TODO switch to a select if more than 3 */}
                                        {tabs.map(({ id, linkText }) => (
                                            <Link
                                                className={
                                                    id === activeTabId ? 'text-link' : 'text-inherit hover:text-link'
                                                }
                                                key={id}
                                                onClick={() => setTabId(id)}
                                            >
                                                {linkText}
                                            </Link>
                                        ))}
                                    </div>
                                )}
                            </div>
                            {/* Setting key forces the component to be recreated when the tab changes */}
                            <QueryTile key={activeTabId} query={query} />
                        </div>
                    )
                } else {
                    return null
                }
            })}
        </div>
    )
}

const QueryTile = ({ query }: { query: QuerySchema }): JSX.Element => {
    if (query.kind === NodeKind.DataTableNode && query.source.kind === NodeKind.WebStatsTableQuery) {
        return <WebStatsTableTile query={query} breakdownBy={query.source.breakdownBy} />
    }

    return <Query query={query} readOnly={true} context={queryContext} />
}

const WebStatsTableTile = ({
    query,
    breakdownBy,
}: {
    query: DataTableNode
    breakdownBy: WebStatsBreakdown
}): JSX.Element => {
    const { togglePropertyFilter } = useActions(webAnalyticsLogic)
    const propertyName = webStatsBreakdownToPropertyName(breakdownBy)

    const onClick = useCallback(
        (record: unknown) => {
            if (typeof record !== 'object' || !record || !('result' in record)) {
                return
            }
            const result = record.result
            if (!Array.isArray(result)) {
                return
            }
            // assume that the first element is the value
            togglePropertyFilter(propertyName, result[0])
        },
        [togglePropertyFilter, propertyName]
    )

    return (
        <Query
            query={query}
            readOnly={true}
            context={{
                ...queryContext,
                rowProps: (record) => ({
                    onClick: () => onClick(record),
                    className: 'hover:underline cursor-pointer hover:bg-mark',
                }),
            }}
        />
    )
}

export const Notice = (): JSX.Element => {
    const { openSupportForm } = useActions(supportLogic)
    const { preflight } = useValues(preflightLogic)

    const showSupportOptions = preflight?.cloud

    return (
        <LemonBanner type={'info'}>
            <p>PostHog Web Analytics is in closed Alpha. Thanks for taking part! We'd love to hear what you think.</p>
            {showSupportOptions ? (
                <p>
                    <Link onClick={() => openSupportForm('bug')}>
                        <IconBugReport /> Report a bug
                    </Link>{' '}
                    -{' '}
                    <Link onClick={() => openSupportForm('feedback')}>
                        <IconFeedback /> Give feedback
                    </Link>{' '}
                    -{' '}
                    <Link to={'https://github.com/PostHog/posthog/issues/18177'}>
                        <IconGithub /> View GitHub issue
                    </Link>
                </p>
            ) : null}
        </LemonBanner>
    )
}

export const WebAnalyticsDashboard = (): JSX.Element => {
    return (
        <div className="w-full flex flex-col pt-2">
            <Notice />
            <Filters />
            <Tiles />
        </div>
    )
}
