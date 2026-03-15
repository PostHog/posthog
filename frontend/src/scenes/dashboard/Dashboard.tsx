import './Dashboard.scss'

import clsx from 'clsx'
import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'

import { IconEllipsis, IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { AccessDenied } from 'lib/components/AccessDenied'
import { NotFound } from 'lib/components/NotFound'
import { useFileSystemLogView } from 'lib/hooks/useFileSystemLogView'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { cn } from 'lib/utils/css-classes'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { DashboardEditBar } from 'scenes/dashboard/DashboardEditBar'
import { DashboardItems } from 'scenes/dashboard/DashboardItems'
import { DashboardLogicProps, dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { DashboardReloadAction, LastRefreshText } from 'scenes/dashboard/DashboardReloadAction'
import { dataThemeLogic } from 'scenes/dataThemeLogic'
import { InsightErrorState } from 'scenes/insights/EmptyStates'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneStickyBar } from '~/layout/scenes/components/SceneStickyBar'
import { ProductKey } from '~/queries/schema/schema-general'
import { DashboardMode, DashboardPlacement, DashboardType, DataColorThemeModel, QueryBasedInsightModel } from '~/types'

import { teamLogic } from '../teamLogic'
import { AddInsightToDashboardModal } from './addInsightToDashboardModal/AddInsightToDashboardModal'
import { addInsightToDashboardLogic } from './addInsightToDashboardModalLogic'
import { DashboardHeader } from './DashboardHeader'
import { DashboardOverridesBanner } from './DashboardOverridesBanner'
import { EmptyDashboardComponent } from './EmptyDashboardComponent'

interface DashboardProps {
    id?: string
    dashboard?: DashboardType<QueryBasedInsightModel>
    placement?: DashboardPlacement
    themes?: DataColorThemeModel[]
    /** When set, the "Edit dashboard" menu item links to the dashboard editor with a back button pointing here. */
    backTo?: { url: string; name: string }
}

// Wrapper needed because SceneComponent<DashboardLogicProps> requires the component to accept
// DashboardLogicProps, but DashboardScene takes { backTo? } (logic props are bound separately).
function DashboardSceneWrapper(): JSX.Element {
    return <DashboardScene />
}

export const scene: SceneExport<DashboardLogicProps> = {
    component: DashboardSceneWrapper,
    logic: dashboardLogic,
    paramsToProps: ({ params: { id, placement } }) => ({
        id: parseInt(id as string),
        placement,
    }),
    productKey: ProductKey.PRODUCT_ANALYTICS,
}

export function Dashboard({ id, dashboard, placement, themes, backTo }: DashboardProps): JSX.Element {
    useMountedLogic(dataThemeLogic({ themes }))

    return (
        <BindLogic logic={dashboardLogic} props={{ id: parseInt(id as string), placement, dashboard }}>
            <DashboardScene backTo={backTo} />
        </BindLogic>
    )
}

function DashboardScene({ backTo }: { backTo?: { url: string; name: string } }): JSX.Element {
    const {
        placement,
        dashboard,
        canEditDashboard,
        tiles,
        itemsLoading,
        dashboardMode,
        dashboardFailedToLoad,
        accessDeniedToDashboard,
        hasVariables,
        refreshAnalysisResult,
        analysisRating,
        showApplyFiltersBanner,
        loadingPreview,
        cancellingPreview,
        hasUrlFilters,
    } = useValues(dashboardLogic)
    const { currentTeamId } = useValues(teamLogic)
    const {
        reportDashboardViewed,
        abortAnyRunningQuery,
        setRefreshAnalysisResult,
        setAnalysisRating,
        applyFilters,
        setDashboardMode,
    } = useActions(dashboardLogic)
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
            {canEditDashboard && addInsightToDashboardModalVisible && <AddInsightToDashboardModal />}

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

                    {refreshAnalysisResult && (
                        <LemonBanner
                            type="info"
                            onClose={() => setRefreshAnalysisResult(null)}
                            className="mb-4 [&>.flex]:items-start"
                            hideIcon
                        >
                            <div className="whitespace-pre-wrap">{refreshAnalysisResult}</div>
                            <div className="flex items-center gap-0.5 mt-2">
                                {analysisRating ? (
                                    <span className="text-muted text-xs">Thanks for the feedback!</span>
                                ) : (
                                    <>
                                        <LemonButton
                                            size="xsmall"
                                            icon={<IconThumbsUp />}
                                            tooltip="Helpful"
                                            onClick={() => setAnalysisRating('up')}
                                        />
                                        <LemonButton
                                            size="xsmall"
                                            icon={<IconThumbsDown />}
                                            tooltip="Not helpful"
                                            onClick={() => setAnalysisRating('down')}
                                        />
                                    </>
                                )}
                            </div>
                        </LemonBanner>
                    )}

                    {showApplyFiltersBanner && (
                        <LemonBanner type="info" className="mb-2">
                            <div className="flex items-center justify-between gap-2">
                                <span>Filters are not automatically applied on large dashboards.</span>
                                <div className="flex gap-2 shrink-0">
                                    <LemonButton
                                        onClick={() =>
                                            setDashboardMode(
                                                hasUrlFilters ? dashboardMode : null,
                                                DashboardEventSource.DashboardHeaderDiscardChanges
                                            )
                                        }
                                        loading={cancellingPreview}
                                        type="secondary"
                                        size="small"
                                    >
                                        Cancel
                                    </LemonButton>
                                    <LemonButton
                                        onClick={applyFilters}
                                        loading={loadingPreview}
                                        type="primary"
                                        size="small"
                                    >
                                        Apply filters
                                    </LemonButton>
                                </div>
                            </div>
                        </LemonBanner>
                    )}

                    <SceneStickyBar showBorderBottom={false}>
                        <div className="flex flex-col md:flex-row gap-2 justify-between">
                            {![
                                DashboardPlacement.Public,
                                DashboardPlacement.Export,
                                DashboardPlacement.FeatureFlag,
                                DashboardPlacement.Group,
                                DashboardPlacement.DataOps,
                                DashboardPlacement.Builtin,
                            ].includes(placement) &&
                                dashboard && <DashboardEditBar />}
                            {![DashboardPlacement.Export, DashboardPlacement.Builtin].includes(placement) && (
                                <div
                                    className={clsx(
                                        'flex shrink-0 deprecated-space-x-4 dashoard-items-actions ml-auto',
                                        {
                                            'mt-7': hasVariables,
                                        }
                                    )}
                                >
                                    <div
                                        className={`left-item ${
                                            placement === DashboardPlacement.Public ? 'text-right' : ''
                                        }`}
                                    >
                                        {[DashboardPlacement.Public].includes(placement) ? (
                                            <LastRefreshText />
                                        ) : !(dashboardMode === DashboardMode.Edit) ? (
                                            <DashboardReloadAction />
                                        ) : null}
                                    </div>
                                    {[
                                        DashboardPlacement.FeatureFlag,
                                        DashboardPlacement.Group,
                                        DashboardPlacement.DataOps,
                                    ].includes(placement) &&
                                        dashboard?.id && (
                                            <LemonMenu
                                                items={[
                                                    {
                                                        label:
                                                            placement === DashboardPlacement.Group
                                                                ? 'Edit dashboard template'
                                                                : 'Edit dashboard',
                                                        to: backTo
                                                            ? `${urls.dashboard(dashboard.id)}?backUrl=${encodeURIComponent(backTo.url)}&backName=${encodeURIComponent(backTo.name)}`
                                                            : urls.dashboard(dashboard.id),
                                                    },
                                                ]}
                                                placement="bottom-end"
                                                fallbackPlacements={['bottom-start', 'bottom']}
                                            >
                                                <LemonButton
                                                    size="small"
                                                    icon={<IconEllipsis className="text-secondary" />}
                                                />
                                            </LemonMenu>
                                        )}
                                </div>
                            )}
                        </div>
                    </SceneStickyBar>

                    <DashboardItems />
                </div>
            )}
        </SceneContent>
    )
}
