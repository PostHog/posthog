import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconFilter } from '@posthog/icons'
import { LemonButton, LemonSwitch, Tooltip } from '@posthog/lemon-ui'

import { FilterBar } from 'lib/components/FilterBar'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { PathCleaningToggle } from 'scenes/web-analytics/PathCleaningToggle'
import { WebConversionGoal } from 'scenes/web-analytics/WebConversionGoal'
import { WebPropertyFilters } from 'scenes/web-analytics/WebPropertyFilters'

import { WebOverviewQuery, WebStatsBreakdown, WebStatsTableQuery } from '~/queries/schema/schema-general'
import { isWebStatsTableQuery } from '~/queries/utils'

export interface WebAnalyticsEditorFiltersProps {
    query: WebStatsTableQuery | WebOverviewQuery
    showing: boolean
    embedded: boolean
}

export function WebAnalyticsEditorFilters({ query, embedded }: WebAnalyticsEditorFiltersProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))

    const isStatsTable = isWebStatsTableQuery(query)
    const isPathBased =
        isStatsTable &&
        [WebStatsBreakdown.Page, WebStatsBreakdown.InitialPage, WebStatsBreakdown.ExitPage].includes(query.breakdownBy)

    return (
        <div className="EditorFiltersWrapper">
            <div
                className={clsx('bg-surface-primary', {
                    'p-4 rounded border': !embedded,
                })}
            >
                <FilterBar
                    showBorderBottom={false}
                    className={clsx('bg-surface-primary')}
                    right={
                        <>
                            <WebConversionGoal
                                value={query.conversionGoal ?? null}
                                onChange={(conversionGoal) =>
                                    updateQuerySource({ conversionGoal } as Partial<typeof query>)
                                }
                            />
                            {isPathBased && (
                                <PathCleaningToggle
                                    value={query.doPathCleaning ?? false}
                                    onChange={(doPathCleaning) =>
                                        updateQuerySource({ doPathCleaning } as Partial<typeof query>)
                                    }
                                />
                            )}
                            <FilterTestAccountsToggle query={query} updateQuerySource={updateQuerySource} />
                            <WebPropertyFilters
                                webAnalyticsFilters={query.properties ?? []}
                                setWebAnalyticsFilters={(properties) => updateQuerySource({ properties })}
                            />
                        </>
                    }
                />
            </div>
        </div>
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
                Filter out internal and test users:{' '}
                <LemonSwitch checked={isFilterTestAccountsEnabled} className="ml-1" />
            </LemonButton>
        </Tooltip>
    )
}
