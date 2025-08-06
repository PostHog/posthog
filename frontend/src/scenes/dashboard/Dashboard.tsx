import './Dashboard.scss'

import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { AccessDenied } from 'lib/components/AccessDenied'
import { NotFound } from 'lib/components/NotFound'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { DashboardEditBar } from 'scenes/dashboard/DashboardEditBar'
import { DashboardItems } from 'scenes/dashboard/DashboardItems'
import { dashboardLogic, DashboardLogicProps } from 'scenes/dashboard/dashboardLogic'
import { DashboardReloadAction, LastRefreshText } from 'scenes/dashboard/DashboardReloadAction'
import { dataThemeLogic } from 'scenes/dataThemeLogic'
import { InsightErrorState } from 'scenes/insights/EmptyStates'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { DashboardMode, DashboardPlacement, DashboardType, DataColorThemeModel, QueryBasedInsightModel } from '~/types'

import { AddInsightToDashboardModal } from './AddInsightToDashboardModal'
import { DashboardHeader } from './DashboardHeader'
import { EmptyDashboardComponent } from './EmptyDashboardComponent'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

interface DashboardProps {
    id?: string
    dashboard?: DashboardType<QueryBasedInsightModel>
    placement?: DashboardPlacement
    themes?: DataColorThemeModel[]
}

export const scene: SceneExport = {
    component: DashboardScene,
    logic: dashboardLogic,
    paramsToProps: ({ params: { id, placement } }: { params: DashboardProps }): DashboardLogicProps => ({
        id: parseInt(id as string),
        placement,
    }),
    settingSectionId: 'environment-product-analytics',
}

export function Dashboard({ id, dashboard, placement, themes }: DashboardProps = {}): JSX.Element {
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
    const { setDashboardMode, reportDashboardViewed, abortAnyRunningQuery } = useActions(dashboardLogic)

    useOnMountEffect(() => {
        reportDashboardViewed()

        // request cancellation of any running queries when this component is no longer in the dom
        return () => abortAnyRunningQuery()
    })

    useKeyboardHotkeys(
        placement == DashboardPlacement.Dashboard
            ? {
                  e: {
                      action: () =>
                          setDashboardMode(
                              dashboardMode === DashboardMode.Edit ? null : DashboardMode.Edit,
                              DashboardEventSource.Hotkey
                          ),
                      disabled: !canEditDashboard || (dashboardMode !== null && dashboardMode !== DashboardMode.Edit),
                  },
                  f: {
                      action: () =>
                          setDashboardMode(
                              dashboardMode === DashboardMode.Fullscreen ? null : DashboardMode.Fullscreen,
                              DashboardEventSource.Hotkey
                          ),
                      disabled: dashboardMode !== null && dashboardMode !== DashboardMode.Fullscreen,
                  },
                  escape: {
                      // Exit edit mode with Esc. Full screen mode is also exited with Esc, but this behavior is native to the browser.
                      action: () => setDashboardMode(null, DashboardEventSource.Hotkey),
                      disabled: dashboardMode !== DashboardMode.Edit,
                  },
              }
            : {},
        [setDashboardMode, dashboardMode, placement]
    )

    if (!dashboard && !itemsLoading && !dashboardFailedToLoad) {
        return <NotFound object="dashboard" />
    }

    if (accessDeniedToDashboard) {
        return <AccessDenied object="dashboard" />
    }

    return (
        <div className="dashboard">
            {placement == DashboardPlacement.Dashboard && <DashboardHeader />}
            {canEditDashboard && <AddInsightToDashboardModal />}

            {dashboardFailedToLoad ? (
                <InsightErrorState title="There was an error loading this dashboard" />
            ) : !tiles || tiles.length === 0 ? (
                <EmptyDashboardComponent loading={itemsLoading} canEdit={canEditDashboard} />
            ) : (
                <div>
                    <div className="Dashboard_filters">
                        <div className="flex gap-2 justify-between">
                            {![
                                DashboardPlacement.Public,
                                DashboardPlacement.Export,
                                DashboardPlacement.FeatureFlag,
                                DashboardPlacement.Group,
                            ].includes(placement) &&
                                dashboard && <DashboardEditBar />}
                            {[DashboardPlacement.FeatureFlag, DashboardPlacement.Group].includes(placement) &&
                                dashboard?.id && (
                                    <LemonButton type="secondary" size="small" to={urls.dashboard(dashboard.id)}>
                                        {placement === DashboardPlacement.Group
                                            ? 'Edit dashboard template'
                                            : 'Edit dashboard'}
                                    </LemonButton>
                                )}
                            {placement !== DashboardPlacement.Export && (
                                <div
                                    className={clsx('flex shrink-0 deprecated-space-x-4 dashoard-items-actions', {
                                        'mt-7': hasVariables,
                                    })}
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
                                </div>
                            )}
                        </div>
                    </div>

                    <DashboardItems />
                </div>
            )}
        </div>
    )
}
