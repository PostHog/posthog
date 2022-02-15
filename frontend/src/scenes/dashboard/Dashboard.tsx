import React, { useEffect } from 'react'
import { SceneLoading } from 'lib/utils'
import { BindLogic, useActions, useValues } from 'kea'
import { dashboardLogic, DashboardLogicProps } from 'scenes/dashboard/dashboardLogic'
import { DashboardItems } from 'scenes/dashboard/DashboardItems'
import { dashboardsModel } from '~/models/dashboardsModel'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CalendarOutlined } from '@ant-design/icons'
import './Dashboard.scss'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { DashboardMode } from '~/types'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { TZIndicator } from 'lib/components/TimezoneAware'
import { EmptyDashboardComponent } from './EmptyDashboardComponent'
import { NotFound } from 'lib/components/NotFound'
import { DashboardReloadAction, LastRefreshText } from 'scenes/dashboard/DashboardReloadAction'
import { SceneExport } from 'scenes/sceneTypes'
import { InsightErrorState } from 'scenes/insights/EmptyStates'
import { DashboardHeader } from './DashboardHeader'

interface Props {
    id?: string
    shareToken?: string
    internal?: boolean
}

export const scene: SceneExport = {
    component: Dashboard,
    logic: dashboardLogic,
    paramsToProps: ({ params: { id } }): DashboardLogicProps => ({ id: parseInt(id) }),
}

export function Dashboard({ id, shareToken, internal }: Props = {}): JSX.Element {
    return (
        <BindLogic logic={dashboardLogic} props={{ id: id ? parseInt(id) : undefined, shareToken, internal }}>
            <DashboardView />
        </BindLogic>
    )
}

function DashboardView(): JSX.Element {
    const {
        dashboard,
        canEditDashboard,
        allItemsLoading: loadingFirstTime,
        items,
        filters: dashboardFilters,
        dashboardMode,
        receivedErrorsFromAPI,
    } = useValues(dashboardLogic)
    const { dashboardsLoading } = useValues(dashboardsModel)
    const { setDashboardMode, setDates, reportDashboardViewed } = useActions(dashboardLogic)

    useEffect(() => {
        reportDashboardViewed()
    }, [])

    useKeyboardHotkeys(
        dashboardMode === DashboardMode.Public || dashboardMode === DashboardMode.Internal
            ? {}
            : {
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
              },
        [setDashboardMode, dashboardMode]
    )

    if (dashboardsLoading || loadingFirstTime) {
        return <SceneLoading />
    }

    if (!dashboard) {
        return <NotFound object="dashboard" />
    }

    return (
        <div className="dashboard">
            {dashboardMode !== DashboardMode.Public && dashboardMode !== DashboardMode.Internal && <DashboardHeader />}
            {receivedErrorsFromAPI ? (
                <InsightErrorState title="There was an error loading this dashboard" />
            ) : !items || items.length === 0 ? (
                <EmptyDashboardComponent />
            ) : (
                <div>
                    <div className="dashboard-items-actions">
                        <div
                            className="left-item"
                            style={dashboardMode === DashboardMode.Public ? { textAlign: 'right' } : undefined}
                        >
                            {dashboardMode === DashboardMode.Public ? <LastRefreshText /> : <DashboardReloadAction />}
                        </div>

                        {dashboardMode !== DashboardMode.Public && (
                            <div
                                className="right-item"
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'flex-end',
                                }}
                            >
                                <TZIndicator style={{ marginRight: 8, fontWeight: 'bold' }} />
                                <DateFilter
                                    defaultValue="Custom"
                                    showCustom
                                    dateFrom={dashboardFilters?.date_from ?? undefined}
                                    dateTo={dashboardFilters?.date_to ?? undefined}
                                    onChange={setDates}
                                    disabled={!canEditDashboard}
                                    makeLabel={(key) => (
                                        <>
                                            <CalendarOutlined />
                                            <span className="hide-when-small"> {key}</span>
                                        </>
                                    )}
                                />
                            </div>
                        )}
                    </div>
                    <DashboardItems />
                </div>
            )}
        </div>
    )
}
