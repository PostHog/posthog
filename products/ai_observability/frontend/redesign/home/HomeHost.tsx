import { useActions, useValues } from 'kea'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { teamLogic } from 'scenes/teamLogic'

import { instrumentationChecklistLogic } from '../../instrumentationChecklist/instrumentationChecklistLogic'
import { ListErrorState } from '../lists/components/ListErrorState'
import { shellScopeLogic } from '../shell/shellScopeLogic'
import { HomeLayout } from './components/HomeLayout'
import { HomeRangeTooLong } from './components/HomeRangeTooLong'
import { InstrumentationRow } from './components/InstrumentationRow'
import { KpiTileChartPanel } from './components/KpiTileChartPanel'
import { KpiTileRow } from './components/KpiTileRow'
import { OpenDashboardLink } from './components/OpenDashboardLink'
import { homeLogic } from './homeLogic'

export function HomeHost(): JSX.Element {
    const logic = homeLogic()
    const {
        metrics,
        metricsLoading,
        metricsFailure,
        dashboardId,
        tileLinks,
        openChartKey,
        openChart,
        openChartInsightUrl,
    } = useValues(logic)
    const { loadMetrics, toggleChart, closeChart } = useActions(logic)
    const { timezone } = useValues(teamLogic)
    const { checklist, checklistBusy, checklistLoading, pendingCheckKey, refreshFailed } =
        useValues(instrumentationChecklistLogic)
    const { dismissCheck, restoreCheck, loadInstrumentationChecklist } = useActions(instrumentationChecklistLogic)
    const { dateFrom, dateTo, filterTestAccounts } = useValues(shellScopeLogic)
    const { setDateRange, setFilterTestAccounts } = useActions(shellScopeLogic)

    const failed = metrics === null && !metricsLoading
    const tiles = !failed ? (
        <>
            <KpiTileRow
                metrics={metrics}
                loading={metricsLoading}
                links={tileLinks}
                openChartKey={openChartKey}
                onToggleChart={toggleChart}
            />
            {metrics && !metricsLoading && openChart && openChartInsightUrl ? (
                <KpiTileChartPanel
                    tile={openChart}
                    bucketStarts={metrics.bucketStarts}
                    bucketSize={metrics.bucketSize}
                    dateFrom={dateFrom}
                    dateTo={dateTo}
                    timezone={timezone}
                    activityUrl={tileLinks[openChart.key]}
                    insightUrl={openChartInsightUrl}
                    onClose={closeChart}
                />
            ) : null}
        </>
    ) : metricsFailure?.kind === 'range_too_long' ? (
        <HomeRangeTooLong detail={metricsFailure.detail} />
    ) : (
        <ListErrorState
            title="Could not load the metrics"
            description="Try again. If it keeps happening, contact support."
            retry={{ onClick: loadMetrics, 'data-attr': 'home-metrics-retry' }}
        />
    )

    return (
        <HomeLayout
            filters={
                <div className="flex flex-wrap items-center gap-2">
                    <DateFilter dateFrom={dateFrom} dateTo={dateTo} onChange={setDateRange} size="small" />
                    <TestAccountFilterSwitch
                        checked={filterTestAccounts}
                        onChange={setFilterTestAccounts}
                        size="small"
                    />
                </div>
            }
            dashboardLink={<OpenDashboardLink dashboardId={dashboardId} />}
            tiles={tiles}
            showComparison={metrics !== null && !metricsLoading}
            instrumentation={
                <InstrumentationRow
                    checklist={checklist}
                    loading={checklistBusy}
                    pendingCheckKey={pendingCheckKey}
                    refreshing={checklistLoading}
                    refreshFailed={refreshFailed}
                    onDismiss={dismissCheck}
                    onRestore={restoreCheck}
                    onRefresh={() => loadInstrumentationChecklist({ refresh: true })}
                />
            }
        />
    )
}
