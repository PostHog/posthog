import { IconAsterisk, IconGlobe, IconMouse, IconPerson, IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { XRayHog2 } from 'lib/components/hedgehogs'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyNumber } from 'lib/utils'
import { useEffect } from 'react'

import { pageReportsLogic } from './pageReportsLogic'
import { Tiles } from './WebAnalyticsDashboard'
import { WebAnalyticsCompareFilter } from './WebAnalyticsFilters'

function NoUrlSelectedMessage(): JSX.Element {
    return (
        <div className="border-2 border-dashed border-primary w-full p-8 rounded flex items-center justify-center gap-8">
            <div className="flex-shrink-0">
                <XRayHog2 alt="X-ray hedgehog" className="w-60" />
            </div>
            <div className="flex-1 max-w-140">
                <h2>Select a page to analyze</h2>
                <p className="ml-0">
                    See detailed performance metrics for any page on your site. Just use the search bar above to find
                    and select a page you want to analyze.
                </p>
            </div>
        </div>
    )
}

export function PageReportsFilters(): JSX.Element {
    const { pagesUrls, pageUrl, isLoading, stripQueryParams, dateFilter } = useValues(pageReportsLogic)
    const { setPageUrl, setPageUrlSearchTerm, toggleStripQueryParams, loadPages, setDates } =
        useActions(pageReportsLogic)

    const options = pagesUrls.map((option: { url: string; count: number }) => ({
        key: option.url,
        label: option.url,
        labelComponent: (
            <div className="flex justify-between items-center w-full">
                <span className="truncate">{option.url}</span>
                <span className="text-muted ml-2">{option.count.toLocaleString()}</span>
            </div>
        ),
    }))

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
                <div className="flex-1">
                    <div className="relative">
                        <IconGlobe className="absolute left-2 top-1/2 -translate-y-1/2 text-muted" />
                        <LemonInputSelect
                            allowCustomValues={false}
                            placeholder="Click or type to see top pages"
                            loading={isLoading}
                            size="small"
                            mode="single"
                            value={pageUrl ? [pageUrl] : null}
                            onChange={(val: string[]) => setPageUrl(val.length > 0 ? val[0] : null)}
                            options={options}
                            onInputChange={(val: string) => setPageUrlSearchTerm(val)}
                            data-attr="page-reports-url-search"
                            onFocus={() => loadPages('')}
                            className="max-w-full pl-8"
                        />
                    </div>
                </div>
                <Tooltip title="Strip query parameters from URLs (e.g. '?utm_source=...'). This will match the base URL regardless of query parameters.">
                    <LemonButton icon={<IconAsterisk />} onClick={toggleStripQueryParams} type="secondary" size="small">
                        Strip query parameters: <LemonSwitch checked={stripQueryParams} className="ml-1" />
                    </LemonButton>
                </Tooltip>
                <DateFilter dateFrom={dateFilter.dateFrom} dateTo={dateFilter.dateTo} onChange={setDates} />
                <WebAnalyticsCompareFilter />
            </div>
        </div>
    )
}

interface StatCardProps {
    title: string
    value: string | number
    icon: React.ReactNode
    tooltip?: string
}

function StatCard({ title, value, icon, tooltip }: StatCardProps): JSX.Element {
    const content = (
        <div className="flex flex-col items-center p-2 border rounded bg-bg-light min-w-16 hover:border-primary transition-colors">
            <div className="flex items-center gap-1 text-xs text-muted mb-1">
                {icon}
                <span>{title}</span>
            </div>
            <div className="text-lg font-semibold">{humanFriendlyNumber(Number(value))}</div>
        </div>
    )

    return tooltip ? (
        <Tooltip title={tooltip} placement="top">
            {content}
        </Tooltip>
    ) : (
        content
    )
}

export function PageStatsRow(): JSX.Element {
    const { pageUrl, stats } = useValues(pageReportsLogic)
    const { loadPageStats } = useActions(pageReportsLogic)

    // Force load stats when component mounts if we have a URL
    useEffect(() => {
        if (pageUrl) {
            loadPageStats(pageUrl)
        }
    }, [pageUrl, loadPageStats])

    if (!pageUrl) {
        return <></>
    }

    // If stats aren't loaded yet, use zeroed/empty values
    const pageStats = stats || {
        pageviews: 0,
        visitors: 0,
        recordings: 0,
        clicks: 0,
        rageClicks: 0,
        deadClicks: 0,
        errors: 0,
        surveysShown: 0,
        surveysAnswered: 0,
    }

    return (
        <div className="grid grid-cols-4 sm:grid-cols-6 md:grid-cols-8 gap-1 my-2">
            <StatCard
                title="Pageviews"
                value={pageStats.pageviews}
                icon={<IconGlobe className="text-primary" />}
                tooltip="Total number of times this page was viewed"
            />
            <StatCard
                title="Visitors"
                value={pageStats.visitors}
                icon={<IconPerson className="text-primary" />}
                tooltip="Unique visitors who viewed this page"
            />
            <StatCard
                title="Recordings"
                value={pageStats.recordings}
                icon={<IconPlayCircle className="text-primary" />}
                tooltip="Session recordings containing this page"
            />
            <StatCard
                title="Clicks"
                value={pageStats.clicks}
                icon={<IconMouse className="text-primary" />}
                tooltip="Total clicks on this page"
            />
            <StatCard
                title="Rage clicks"
                value={pageStats.rageClicks}
                icon={<IconWarning className="text-warning" />}
                tooltip="Multiple rapid clicks in the same area"
            />
            <StatCard
                title="Dead clicks"
                value={pageStats.deadClicks}
                icon={<IconAsterisk className="text-primary" />}
                tooltip="Clicks that didn't result in any action"
            />
            <StatCard
                title="Errors"
                value={pageStats.errors}
                icon={<IconWarning className="text-danger" />}
                tooltip="JavaScript exceptions on this page"
            />
            <StatCard
                title="Surveys"
                value={`${pageStats.surveysAnswered}/${pageStats.surveysShown}`}
                icon={<IconGlobe className="text-primary" />}
                tooltip="Surveys answered vs. shown on this page"
            />
        </div>
    )
}

export function PageReports(): JSX.Element {
    const { hasPageUrl, tiles } = useValues(pageReportsLogic)

    if (!hasPageUrl) {
        return (
            <div className="space-y-2 mt-2">
                <NoUrlSelectedMessage />
            </div>
        )
    }

    return (
        <div className="space-y-2 mt-2 h-full min-h-0">
            <PageStatsRow />
            <Tiles tiles={tiles} compact={true} />
        </div>
    )
}
