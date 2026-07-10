import './Dashboard.scss'

import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { Suspense } from 'react'

import { AccessDenied } from 'lib/components/AccessDenied'
import { NotFound } from 'lib/components/NotFound'
import { useFileSystemLogView } from 'lib/hooks/useFileSystemLogView'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { cn } from 'lib/utils/css-classes'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { DashboardFilterBar } from 'scenes/dashboard/DashboardFilters'
import { DashboardItems } from 'scenes/dashboard/DashboardItems'
import { DashboardLogicProps, dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { dataThemeLogic } from 'scenes/dataThemeLogic'
import { InsightErrorState } from 'scenes/insights/EmptyStates'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneStickyBar } from '~/layout/scenes/components/SceneStickyBar'
import { ProductKey } from '~/queries/schema/schema-general'
import { DashboardPlacement, DashboardType, DataColorThemeModel, QueryBasedInsightModel } from '~/types'

import { teamLogic } from '../teamLogic'
import { addInsightToDashboardLogic } from './addInsightToDashboardModalLogic'
import { DashboardHeader } from './DashboardHeader'
import { DashboardOverridesBanner } from './DashboardOverridesBanner'
import { DashboardPublicAccessBanner } from './DashboardPublicAccessBanner'
import { DashboardZoomControl } from './DashboardZoomControl'
import { EmptyDashboardComponent } from './EmptyDashboardComponent'

// Only shown after a user opens the "add insight" modal — keep its saved-insights picker off
// the dashboard's eager load path.
const AddInsightToDashboardModal = lazyWithRetry(() =>
    import('./addInsightToDashboardModal/AddInsightToDashboardModal').then((module) => ({
        default: module.AddInsightToDashboardModal,
    }))
)

interface DashboardProps {
    id?: string
    dashboard?: DashboardType<QueryBasedInsightModel>
    placement?: DashboardPlacement
    themes?: DataColorThemeModel[]
    /** When set, the "Edit dashboard" menu item links to the dashboard editor with a back button pointing here. */
    backTo?: { url: string; name: string }
    showCreateAnomalyAlertButton?: boolean
}

const parseDashboardId = (id: string | undefined): number => (typeof id === 'string' ? parseInt(id, 10) : NaN)

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
        layoutEditMode,
        dashboardFailedToLoad,
        accessDeniedToDashboard,
    } = useValues(dashboardLogic)
    const { layoutZoom } = useValues(dashboardLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { reportDashboardViewed, abortAnyRunningQuery, setLayoutZoom } = useActions(dashboardLogic)
    const { addInsightToDashboardModalVisible } = useValues(addInsightToDashboardLogic)

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

    if (!dashboard && !itemsLoading && !dashboardFailedToLoad) {
        return <NotFound object="dashboard" />
    }

    if (accessDeniedToDashboard) {
        return <AccessDenied object="dashboard" />
    }

    return (
        <SceneContent className={cn('dashboard')}>
            {placement == DashboardPlacement.Dashboard && <DashboardHeader />}
            {canEditDashboard && addInsightToDashboardModalVisible && (
                <Suspense fallback={null}>
                    <AddInsightToDashboardModal />
                </Suspense>
            )}
            <DashboardPublicAccessBanner dashboard={dashboard} placement={placement} />

            {dashboardFailedToLoad ? (
                <InsightErrorState title="There was an error loading this dashboard" />
            ) : !tiles || tiles.length === 0 ? (
                <EmptyDashboardComponent loading={itemsLoading} canEdit={canEditDashboard} />
            ) : (
                <div
                    className={cn({
                        '-mt-4': placement == DashboardPlacement.ProjectHomepage,
                    })}
                >
                    <DashboardOverridesBanner />

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
