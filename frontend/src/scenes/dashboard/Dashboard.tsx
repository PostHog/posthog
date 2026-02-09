import './Dashboard.scss'

import clsx from 'clsx'
import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessDenied } from 'lib/components/AccessDenied'
import { NotFound } from 'lib/components/NotFound'
import { useFileSystemLogView } from 'lib/hooks/useFileSystemLogView'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { cn } from 'lib/utils/css-classes'
import { DashboardEditBar } from 'scenes/dashboard/DashboardEditBar'
import {
    DashboardAdvancedOptions,
    DashboardAdvancedOptionsToggle,
    DashboardPrimaryFilters,
    DashboardQuickFiltersRow,
} from 'scenes/dashboard/DashboardFilters'
import { DashboardItems } from 'scenes/dashboard/DashboardItems'
import { DashboardReloadAction, LastRefreshText } from 'scenes/dashboard/DashboardReloadAction'
import { useDashboardFiltersEnabled } from 'scenes/dashboard/dashboardFiltersEnabled'
import { DashboardLogicProps, dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { dataThemeLogic } from 'scenes/dataThemeLogic'
import { InsightErrorState } from 'scenes/insights/EmptyStates'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneStickyBar } from '~/layout/scenes/components/SceneStickyBar'
import { ProductKey } from '~/queries/schema/schema-general'
import { DashboardMode, DashboardPlacement, DashboardType, DataColorThemeModel, QueryBasedInsightModel } from '~/types'

import { teamLogic } from '../teamLogic'
import { AddInsightToDashboardModal } from './AddInsightToDashboardModal'
import { DashboardHeader } from './DashboardHeader'
import { DashboardOverridesBanner } from './DashboardOverridesBanner'
import { EmptyDashboardComponent } from './EmptyDashboardComponent'

interface DashboardProps {
    id?: string
    dashboard?: DashboardType<QueryBasedInsightModel>
    placement?: DashboardPlacement
    themes?: DataColorThemeModel[]
}

export const scene: SceneExport<DashboardLogicProps> = {
    component: DashboardScene,
    logic: dashboardLogic,
    paramsToProps: ({ params: { id, placement } }) => ({
        id: parseInt(id as string),
        placement,
    }),
    productKey: ProductKey.PRODUCT_ANALYTICS,
}

export function Dashboard({ id, dashboard, placement, themes }: DashboardProps): JSX.Element {
    useMountedLogic(dataThemeLogic({ themes }))

    return (
        <BindLogic logic={dashboardLogic} props={{ id: parseInt(id as string), placement, dashboard }}>
            <DashboardScene />
        </BindLogic>
    )
}

function DashboardScene(): JSX.Element {
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
    } = useValues(dashboardLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { reportDashboardViewed, abortAnyRunningQuery } = useActions(dashboardLogic)
    const dashboardFiltersEnabled = useDashboardFiltersEnabled()

    useFileSystemLogView({
        type: 'dashboard',
        ref: dashboard?.id,
        enabled: Boolean(currentTeamId && dashboard?.id && !dashboardFailedToLoad && !accessDeniedToDashboard),
        deps: [currentTeamId, dashboard?.id, dashboardFailedToLoad, accessDeniedToDashboard],
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
            {canEditDashboard && <AddInsightToDashboardModal />}

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

                    <SceneStickyBar showBorderBottom={false}>
                        <div className="flex flex-col gap-2 w-full">
                            {/* Primary row: Date + QF Icon (left) + Advanced toggle + Refresh (right) */}
                            <div className="flex gap-2 justify-between">
                                <div className="flex items-start gap-2 flex-wrap w-full">
                                    {![
                                        DashboardPlacement.Public,
                                        DashboardPlacement.Export,
                                        DashboardPlacement.FeatureFlag,
                                        DashboardPlacement.Group,
                                        DashboardPlacement.Builtin,
                                    ].includes(placement) &&
                                        dashboard &&
                                        (dashboardFiltersEnabled ? <DashboardPrimaryFilters /> : <DashboardEditBar />)}
                                </div>
                                {[DashboardPlacement.FeatureFlag, DashboardPlacement.Group].includes(placement) &&
                                    dashboard?.id && (
                                        <LemonButton type="secondary" size="small" to={urls.dashboard(dashboard.id)}>
                                            {placement === DashboardPlacement.Group
                                                ? 'Edit dashboard template'
                                                : 'Edit dashboard'}
                                        </LemonButton>
                                    )}
                                {![DashboardPlacement.Export, DashboardPlacement.Builtin].includes(placement) && (
                                    <div
                                        className={clsx('flex shrink-0 gap-4 items-center dashoard-items-actions', {
                                            'mt-7': hasVariables,
                                        })}
                                    >
                                        {dashboardFiltersEnabled && <DashboardAdvancedOptionsToggle />}
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
                                    </div>
                                )}
                            </div>

                            {/* Quick filters row - full width */}
                            {dashboardFiltersEnabled && (
                                <div className="flex items-center gap-2 flex-wrap">
                                    <DashboardQuickFiltersRow />
                                </div>
                            )}

                            {/* Advanced options row - full width */}
                            {dashboardFiltersEnabled && <DashboardAdvancedOptions />}
                        </div>
                    </SceneStickyBar>

                    <DashboardItems />
                </div>
            )}
        </SceneContent>
    )
}
