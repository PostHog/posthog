import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo, useRef } from 'react'

import { Spinner } from '@posthog/quill'
import { ChartThemeProvider } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sampleDataStateLogic } from 'scenes/insights/EmptyStates/sampleDataStateLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { DashboardActions } from '../dashboard/actions/DashboardActions'
import { DashboardUnavailable } from '../dashboard/core/DashboardUnavailable'
import { DashboardView } from '../dashboard/core/DashboardView'
import { SaveConflictDialog } from '../dashboard/saved/SaveConflictDialog'
import { savedDashboardLogic } from '../dashboard/saved/savedDashboardLogic'
import { SaveStatus } from '../dashboard/saved/SaveStatus'
import { ANALYTICS_FILTER_TYPES } from '../filters/analytics/analyticsFilterTypes'
import { useDashboardFilters } from '../filters/useDashboardFilters'
import { runSampleQuery } from '../fixtures/runSampleQuery'
import { createChartPanel } from '../panels/chart/createChartPanel'
import { markdownPanel } from '../panels/markdown/markdownSpec'
import { createQueryBatchRunner } from '../query/queryBatchRunner'
import {
    type DashboardSceneLogicProps,
    KITCHEN_SINK_CUSTOM_PANEL,
    savedDashboardLogicProps,
    dashboardSceneLogic,
} from './dashboardSceneLogic'

export const scene: SceneExport = {
    component: DashboardScene,
    logic: dashboardSceneLogic,
    paramsToProps: ({ params: { uid } }): DashboardSceneLogicProps => ({ uid }),
}

export function DashboardScene({ uid }: DashboardSceneLogicProps): JSX.Element {
    return (
        <FlaggedFeature flag={FEATURE_FLAGS.DASHBOARDS_V2} fallback={<NotFound object="page" />}>
            <BindLogic logic={savedDashboardLogic} props={savedDashboardLogicProps({ uid })}>
                <DashboardV2 />
            </BindLogic>
        </FlaggedFeature>
    )
}

function DashboardV2(): JSX.Element {
    const { dashboard, disabledReasonFor, canUndo, canRedo, unavailable } = useValues(savedDashboardLogic)
    const { undo, redo } = useActions(savedDashboardLogic)
    const { activeTabId } = useValues(dashboardSceneLogic)
    const { applyDashboardEdit, setActiveTab } = useActions(dashboardSceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    // The app theme adds the tooltip z-index above app overlays and the Storybook snapshot switch.
    const chartTheme = useChartTheme()
    const { currentTeamId, timezone } = useValues(teamLogic)
    const tabRef = useRef(activeTabId)
    tabRef.current = activeTabId
    const { currentOrganization } = useValues(organizationLogic)
    const organizationRef = useRef(currentOrganization)
    organizationRef.current = currentOrganization
    // The same check as v1 insights: a project that has sent no events yet sees sample charts instead of empty ones.
    const { shouldShowSampleData } = useValues(sampleDataStateLogic)
    // TODO(2026-11-25): Remove with the kitchen sink fixture, once the board list can open saved boards.
    // Lets the "Tile states" tab show the sample data state in a project that already has events.
    const { searchParams } = useValues(router)
    const forceSampleData = searchParams.sample_data === true || searchParams.sample_data === 'true'
    // The same pair of flags as the v1 dashboard query layer: the project turns it on, the person sees it.
    const runsRealQueries =
        !!featureFlags[FEATURE_FLAGS.DASHBOARD_V2] &&
        !!featureFlags[FEATURE_FLAGS.DASHBOARD_V2_USERS] &&
        !!currentTeamId
    const sampleData = shouldShowSampleData || forceSampleData
    // The chart cache is keyed by runner, so a runner per visit drops results checked against this person's access
    // when they leave, instead of showing them again after their access changes.
    const panels = useMemo(() => {
        const runQuery =
            runsRealQueries && currentTeamId
                ? createQueryBatchRunner(currentTeamId, {
                      context: () => ({ dashboard_tab_id: tabRef.current }),
                      allowsProject: (project) =>
                          !!organizationRef.current?.teams.some(
                              (team) => team.id === project || team.project_id === project
                          ),
                  })
                : runSampleQuery
        return [createChartPanel({ runQuery, sampleData }), markdownPanel, KITCHEN_SINK_CUSTOM_PANEL]
    }, [runsRealQueries, currentTeamId, sampleData])
    // TODO(2026-11-25): Offer filters with real queries once the query batch request carries them; until then only the
    // sample runner applies them, so a filter bar there would narrow nothing.
    const { filters, timeRange } = useDashboardFilters({
        types: runsRealQueries ? undefined : ANALYTICS_FILTER_TYPES,
        time: { timezone },
    })
    if (!dashboard) {
        return unavailable ? (
            <DashboardUnavailable problem={unavailable} />
        ) : (
            <div className="flex justify-center p-8">
                <Spinner />
            </div>
        )
    }
    return (
        <ChartThemeProvider value={chartTheme}>
            <DashboardView
                surface="dashboard-v2-scene"
                dashboard={dashboard}
                activeTabId={activeTabId}
                panels={panels}
                disabledReasonFor={disabledReasonFor}
                onEdit={applyDashboardEdit}
                onActiveTabChange={setActiveTab}
                history={{ canUndo, canRedo, onUndo: undo, onRedo: redo }}
                refresh={{}}
                filters={filters}
                timeRange={timeRange}
                header={
                    <header className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex flex-col gap-1 min-w-0">
                            <h1 className="text-lg font-semibold m-0">{dashboard.title}</h1>
                            {dashboard.description && (
                                <p className="text-sm text-muted-foreground m-0">{dashboard.description}</p>
                            )}
                        </div>
                        <div className="flex items-center gap-2">
                            <SaveStatus />
                            <DashboardActions />
                        </div>
                    </header>
                }
            />
            <SaveConflictDialog />
        </ChartThemeProvider>
    )
}
