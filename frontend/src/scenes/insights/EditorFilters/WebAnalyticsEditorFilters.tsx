import { useActions, useValues } from 'kea'

import { IconFilter, IconGear } from '@posthog/icons'
import { LemonButton, LemonSwitch, Link, Tooltip } from '@posthog/lemon-ui'

import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { FilterBar } from 'lib/components/FilterBar'
import { IconBranch } from 'lib/lemon-ui/icons/icons'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'
import { WebConversionGoal } from 'scenes/web-analytics/WebConversionGoal'
import { WebPropertyFilters } from 'scenes/web-analytics/WebPropertyFilters'

import { WebOverviewQuery, WebStatsBreakdown, WebStatsTableQuery } from '~/queries/schema/schema-general'
import { isWebStatsTableQuery } from '~/queries/utils'
import { AvailableFeature } from '~/types'

import { WebAnalyticsBreakdownSelector } from './WebAnalyticsBreakdownSelector'

export interface WebAnalyticsEditorFiltersProps {
    query: WebStatsTableQuery | WebOverviewQuery
    showing: boolean
    embedded: boolean
}

export function WebAnalyticsEditorFilters({ query, showing }: WebAnalyticsEditorFiltersProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))

    const isStatsTable = isWebStatsTableQuery(query)
    const isPathBased =
        isStatsTable &&
        [WebStatsBreakdown.Page, WebStatsBreakdown.InitialPage, WebStatsBreakdown.ExitPage].includes(query.breakdownBy)

    if (!showing) {
        return null
    }

    return (
        <FilterBar
            left={
                <>
                    {isStatsTable && (
                        <WebAnalyticsBreakdownSelector
                            value={query.breakdownBy}
                            onChange={(breakdownBy) => updateQuerySource({ breakdownBy })}
                        />
                    )}
                </>
            }
            right={
                <>
                    <CompareFilter
                        compareFilter={query.compareFilter}
                        updateCompareFilter={(compareFilter) => updateQuerySource({ compareFilter })}
                    />
                    <WebConversionGoal
                        value={query.conversionGoal ?? null}
                        onChange={(conversionGoal) => updateQuerySource({ conversionGoal })}
                    />
                    {isPathBased && <PathCleaningToggle query={query} updateQuerySource={updateQuerySource} />}
                    <FilterTestAccountsToggle query={query} updateQuerySource={updateQuerySource} />
                    <WebPropertyFilters
                        webAnalyticsFilters={query.properties ?? []}
                        setWebAnalyticsFilters={(properties) => updateQuerySource({ properties })}
                    />
                </>
            }
        />
    )
}

function PathCleaningToggle({
    query,
    updateQuerySource,
}: {
    query: WebStatsTableQuery | WebOverviewQuery
    updateQuerySource: (updates: Partial<WebStatsTableQuery | WebOverviewQuery>) => void
}): JSX.Element | null {
    const { hasAvailableFeature } = useValues(userLogic)
    const hasAdvancedPaths = hasAvailableFeature(AvailableFeature.PATHS_ADVANCED)

    if (!hasAdvancedPaths) {
        return null
    }

    const isPathCleaningEnabled = query.doPathCleaning ?? false

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
                onClick={() => updateQuerySource({ doPathCleaning: !isPathCleaningEnabled })}
                type="secondary"
                size="small"
            >
                Path cleaning: <LemonSwitch checked={isPathCleaningEnabled} className="ml-1" />
            </LemonButton>
        </Tooltip>
    )
}

function FilterTestAccountsToggle({
    query,
    updateQuerySource,
}: {
    query: WebStatsTableQuery | WebOverviewQuery
    updateQuerySource: (updates: Partial<WebStatsTableQuery | WebOverviewQuery>) => void
}): JSX.Element {
    const isFilterTestAccountsEnabled = query.filterTestAccounts ?? false

    return (
        <Tooltip title="Filter out events from test accounts">
            <LemonButton
                icon={<IconFilter />}
                onClick={() => updateQuerySource({ filterTestAccounts: !isFilterTestAccountsEnabled })}
                type="secondary"
                size="small"
            >
                Filter test accounts: <LemonSwitch checked={isFilterTestAccountsEnabled} className="ml-1" />
            </LemonButton>
        </Tooltip>
    )
}
