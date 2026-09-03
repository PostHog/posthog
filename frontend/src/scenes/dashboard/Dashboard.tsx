import './Dashboard.scss'

import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'

import { AccessDenied } from 'lib/components/AccessDenied'
import { dashboardTileScreenshotKey } from 'lib/components/Cards/InsightCard/insightCardImageCapture'
import { NotFound } from 'lib/components/NotFound'
import { ScreenShotEditor } from 'lib/components/TakeScreenshot/ScreenShotEditor'
import { useFileSystemLogView } from 'lib/hooks/useFileSystemLogView'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { Link } from 'lib/lemon-ui/Link'
import { cn } from 'lib/utils/css-classes'
import { DashboardFilterBar } from 'scenes/dashboard/DashboardFilters'
import { DashboardItems } from 'scenes/dashboard/DashboardItems'
import { DashboardLoadAction, DashboardLogicProps, dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { dataThemeLogic } from 'scenes/dataThemeLogic'
import { InsightErrorState } from 'scenes/insights/EmptyStates'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneStickyBar } from '~/layout/scenes/components/SceneStickyBar'
import { ProductKey } from '~/queries/schema/schema-general'
import { DashboardPlacement, DashboardType, DataColorThemeModel, QueryBasedInsightModel } from '~/types'

import { dashboardAgentContextForPlacement } from 'products/dashboards/frontend/dashboardAgentContext'
import { useAttachedContext } from 'products/posthog_ai/frontend/api/logics'

import { teamLogic } from '../teamLogic'
import { AddInsightToDashboardModal } from './addInsightToDashboardModal/AddInsightToDashboardModal'
import { addInsightToDashboardLogic } from './addInsightToDashboardModalLogic'
import { DashboardAiSync } from './DashboardAiSync'
import { DashboardHeader } from './DashboardHeader'
import { DashboardOverridesBanner } from './DashboardOverridesBanner'
import { DashboardPublicAccessBanner } from './DashboardPublicAccessBanner'
import { DashboardRetentionBanner } from './DashboardRetentionBanner'
import { dashboardSubscribeNudgeLogic } from './dashboardSubscribeNudgeLogic'
import { DashboardZoomControl } from './DashboardZoomControl'
import { EmptyDashboardComponent } from './EmptyDashboardComponent'

// Mount-only: runs the subscribe-nudge eligibility machinery for this dashboard; renders nothing.
function DashboardSubscribeNudgeTrigger({ dashboardId }: { dashboardId: number }): null {
    useMountedLogic(dashboardSubscribeNudgeLogic({ dashboardId }))
    return null
}

interface DashboardProps {
    id?: string
    dashboard?: DashboardType<QueryBasedInsightModel>
    placement?: DashboardPlacement
    themes?: DataColorThemeModel[]
    /** When set, the "Edit dashboard" menu item links to the dashboard editor with a back button pointing here. */
    backTo?: { url: string; name: string }
    showCreateAnomalyAlertButton?: boolean
}

export const parseDashboardId = (id: string | undefined): number => {
    if (!id || !/^\d+$/.test(id)) {
        return NaN
    }
    // Reject "0" and all-zero variants: id 0 is the reserved internal sentinel, never a real dashboard.
    const dashboardId = Number(id)
    return dashboardId > 0 ? dashboardId : NaN
}

// Wrapper needed because SceneComponent<DashboardLogicProps> requires the component to accept
// DashboardLogicProps, but DashboardScene takes { backTo? } (logic props are bound separately).
function DashboardSceneWrapper(): JSX.Element {
    return <DashboardScene />
}

export const scene: SceneExport<DashboardLogicProps> = {
    component: DashboardSceneWrapper,
    logic: dashboardLogic,
    paramsToProps: ({ params: { id, placement } }) => ({ id: parseDashboardId(id), placement }),
    productKey: ProductKey.PRODUCT_ANALYTICS,
}

export function Dashboard({
    id,
    dashboard,
    placement,
    themes,
    backTo,
    showCreateAnomalyAlertButton,
}: DashboardProps): JSX.Element {
    useMountedLogic(dataThemeLogic({ themes }))

    return (
        <BindLogic logic={dashboardLogic} props={{ id: parseDashboardId(id), placement, dashboard }}>
            <DashboardScene backTo={backTo} showCreateAnomalyAlertButton={showCreateAnomalyAlertButton} />
        </BindLogic>
    )
}

function DashboardScene({
    backTo,
    showCreateAnomalyAlertButton,
}: {
    backTo?: { url: string; name: string }
    showCreateAnomalyAlertButton?: boolean
}): JSX.Element {
    const {
        placement,
        dashboard,
        canEditDashboard,
        tiles,
        itemsLoading,
        dashboardLoading,
        layoutEditMode,
        dashboardFailedToLoad,
        accessDeniedToDashboard,
        error404,
        hasInvalidDashboardId,
    } = useValues(dashboardLogic)
    const { layoutZoom } = useValues(dashboardLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { reportDashboardViewed, abortAnyRunningQuery, loadDashboard, setLayoutZoom } = useActions(dashboardLogic)
    const { addInsightToDashboardModalVisible } = useValues(addInsightToDashboardLogic)

    useAttachedContext(dashboardAgentContextForPlacement(dashboard, placement))

    useFileSystemLogView({
        type: 'dashboard',
        ref: dashboard?.id,
        enabled: Boolean(currentTeamId && dashboard?.id && !dashboardFailedToLoad && !accessDeniedToDashboard),
    })

    useOnMountEffect(() => {
        reportDashboardViewed()

        // request cancellation of any running queries when this component is no longer in the dom
        return () => abortAnyRunningQuery()
    })

    // `error404` only becomes true once a load has settled as a 404, so pending loads fall through to the empty/loading state
    if (error404 && !dashboard && !dashboardFailedToLoad) {
        return (
            <NotFound
                object="dashboard"
                caption={
                    <>
                        {hasInvalidDashboardId
                            ? 'This dashboard link is not valid.'
                            : 'It may have been deleted, or the link is out of date.'}{' '}
                        <Link to={urls.dashboards()}>Go to your dashboards</Link>.
                    </>
                }
            />
        )
    }

    if (accessDeniedToDashboard) {
        return <AccessDenied object="dashboard" />
    }

    return (
        <SceneContent className={cn('dashboard')}>
            {placement == DashboardPlacement.Dashboard && (
                <DashboardHeader loading={!dashboard && !dashboardFailedToLoad} />
            )}
            {placement === DashboardPlacement.Dashboard && dashboard?.id ? (
                <DashboardAiSync dashboardId={dashboard.id} />
            ) : null}
            {placement == DashboardPlacement.Dashboard && !!dashboard?.id && (
                <DashboardSubscribeNudgeTrigger dashboardId={dashboard.id} />
            )}
            {canEditDashboard && addInsightToDashboardModalVisible && <AddInsightToDashboardModal />}
            {/* Lets a tile copied as a PNG be annotated before it is shared. Export placement renders headlessly. */}
            {placement !== DashboardPlacement.Export && (
                <ScreenShotEditor screenshotKey={dashboardTileScreenshotKey(dashboard?.id)} />
            )}
            <DashboardPublicAccessBanner dashboard={dashboard} placement={placement} />

            {dashboardFailedToLoad ? (
                <InsightErrorState
                    title="There was an error loading this dashboard"
                    onRetry={
                        placement === DashboardPlacement.Export
                            ? undefined
                            : () => loadDashboard({ action: DashboardLoadAction.Update })
                    }
                    retryLoading={dashboardLoading}
                    placement={placement}
                />
            ) : !tiles || tiles.length === 0 ? (
                <EmptyDashboardComponent loading={itemsLoading || !dashboard} canEdit={canEditDashboard} />
            ) : (
                <div
                    className={cn({
                        '-mt-4': placement == DashboardPlacement.ProjectHomepage,
                    })}
                >
                    <DashboardOverridesBanner />
                    <DashboardRetentionBanner />

                    <SceneStickyBar showBorderBottom={false} className="flex gap-2 space-y-0">
                        <DashboardFilterBar backTo={backTo} />
                        {layoutEditMode &&
                            canEditDashboard &&
                            [
                                DashboardPlacement.Dashboard,
                                DashboardPlacement.ProjectHomepage,
                                DashboardPlacement.Builtin,
                            ].includes(placement) && (
                                <DashboardZoomControl layoutZoom={layoutZoom} setLayoutZoom={setLayoutZoom} />
                            )}
                    </SceneStickyBar>

                    <DashboardItems showCreateAnomalyAlertButton={showCreateAnomalyAlertButton} />
                </div>
            )}
        </SceneContent>
    )
}
