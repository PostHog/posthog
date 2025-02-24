import { IconFilter, IconGear, IconGlobe } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonSwitch, Link, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { authorizedUrlListLogic, AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { IconBranch } from 'lib/lemon-ui/icons/icons'
import { LemonSegmentedSelect } from 'lib/lemon-ui/LemonSegmentedSelect'
import { useState } from 'react'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { ReloadAll } from '~/queries/nodes/DataNode/Reload'
import { AvailableFeature, PropertyMathType } from '~/types'

import { TableSortingIndicator } from './TableSortingIndicator'
import { WebAnalyticsLiveUserCount } from './WebAnalyticsLiveUserCount'
import { ProductTab, webAnalyticsLogic } from './webAnalyticsLogic'
import { WebConversionGoal } from './WebConversionGoal'
import { WebPropertyFilters } from './WebPropertyFilters'

export const WebAnalyticsFilters = (): JSX.Element => {
    const [expanded, setExpanded] = useState(false)

    const { authorizedUrls } = useValues(
        authorizedUrlListLogic({ type: AuthorizedUrlListType.WEB_ANALYTICS, actionId: null, experimentId: null })
    )
    const { domainFilter } = useValues(webAnalyticsLogic)
    const { setDomainFilter } = useActions(webAnalyticsLogic)

    return (
        <div className="flex flex-col md:flex-row md:justify-between gap-2">
            <div className="flex items-start shrink-0">
                <div className="flex flex-1 flex-row gap-2 items-center">
                    <div className="flex flex-row gap-1 items-center flex-1 md:flex-none">
                        <ReloadAll iconOnly />
                        <LemonSelect
                            className="grow md:grow-0"
                            size="small"
                            value={domainFilter || 'all'}
                            icon={<IconGlobe />}
                            onChange={(value) => setDomainFilter(value)}
                            disabled={authorizedUrls.length === 0}
                            options={[
                                {
                                    options: [
                                        { label: 'All domains', value: 'all' },
                                        ...authorizedUrls.map((url) => ({ label: url, value: url })),
                                    ],
                                    footer: (
                                        <span className="text-xs px-2">
                                            Have more domains? Go to{' '}
                                            <Link to={urls.settings('environment', 'web-analytics-authorized-urls')}>
                                                settings
                                            </Link>
                                        </span>
                                    ),
                                },
                            ]}
                        />
                    </div>

                    <div className="hidden md:flex items-center gap-2">
                        <span className="text-muted-alt">|</span>
                        <WebAnalyticsLiveUserCount />
                    </div>

                    <LemonButton
                        type="secondary"
                        size="small"
                        className="sm:hidden"
                        onClick={() => setExpanded((expanded) => !expanded)}
                        icon={<IconFilter />}
                    />
                </div>
            </div>

            {/* On more than mobile, just display Foldable Fields, on smaller delegate displaying it to the expanded state */}
            <div className="hidden sm:flex gap-2">
                <FoldableFilters />
            </div>

            <div
                className={clsx(
                    'flex sm:hidden flex-col gap-2 overflow-hidden transition-all duration-200',
                    expanded ? 'max-h-[500px]' : 'max-h-0'
                )}
            >
                <FoldableFilters />
            </div>
        </div>
    )
}

const FoldableFilters = (): JSX.Element => {
    const {
        webAnalyticsFilters,
        dateFilter: { dateTo, dateFrom },
        compareFilter,
        productTab,
        webVitalsPercentile,
    } = useValues(webAnalyticsLogic)
    const { setWebAnalyticsFilters, setDates, setCompareFilter, setWebVitalsPercentile } = useActions(webAnalyticsLogic)

    const { hasAvailableFeature } = useValues(userLogic)
    const hasAdvancedPaths = hasAvailableFeature(AvailableFeature.PATHS_ADVANCED)

    return (
        <div className="flex flex-row md:flex-row-reverse flex-wrap gap-2 md:[&>*]:grow-0 [&>*]:grow w-full">
            <DateFilter dateFrom={dateFrom} dateTo={dateTo} onChange={setDates} allowTimePrecision={true} />

            {productTab === ProductTab.ANALYTICS ? (
                <>
                    <CompareFilter compareFilter={compareFilter} updateCompareFilter={setCompareFilter} />
                    <WebConversionGoal />
                    <TableSortingIndicator />
                </>
            ) : (
                <LemonSegmentedSelect
                    size="small"
                    value={webVitalsPercentile}
                    onChange={setWebVitalsPercentile}
                    options={[
                        { value: PropertyMathType.P75, label: 'P75' },
                        {
                            value: PropertyMathType.P90,
                            label: (
                                <Tooltip title="P90 is recommended by the standard as a good baseline" delayMs={0}>
                                    P90
                                </Tooltip>
                            ),
                        },
                        { value: PropertyMathType.P99, label: 'P99' },
                    ]}
                />
            )}

            {hasAdvancedPaths && <PathCleaningToggle />}

            <WebPropertyFilters
                setWebAnalyticsFilters={setWebAnalyticsFilters}
                webAnalyticsFilters={webAnalyticsFilters}
            />
        </div>
    )
}

const PathCleaningToggle = (): JSX.Element => {
    const { isPathCleaningEnabled } = useValues(webAnalyticsLogic)
    const { setIsPathCleaningEnabled } = useActions(webAnalyticsLogic)

    return (
        <Tooltip
            title={
                <div className="p-2">
                    <p className="mb-2">
                        Path cleaning helps standardize URLs by removing unnecessary parameters and fragments.
                    </p>
                    <div className="mb-2">
                        <Link to="https://posthog.com/docs/product-analytics/paths#path-cleaning-rules">
                            Learn more about path cleaning rules
                        </Link>
                    </div>
                    <LemonButton
                        icon={<IconGear />}
                        type="primary"
                        size="small"
                        to={urls.settings('project-product-analytics', 'path-cleaning')}
                        targetBlank
                        className="w-full"
                    >
                        Edit path cleaning settings
                    </LemonButton>
                </div>
            }
            placement="top"
            interactive={true}
        >
            <LemonButton
                icon={<IconBranch />}
                onClick={() => setIsPathCleaningEnabled(!isPathCleaningEnabled)}
                type="secondary"
                size="small"
            >
                Path cleaning: <LemonSwitch checked={isPathCleaningEnabled} className="ml-1" />
            </LemonButton>
        </Tooltip>
    )
}
