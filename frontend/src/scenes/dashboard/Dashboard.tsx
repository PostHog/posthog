import React, { useEffect } from 'react'
import { BindLogic, useActions, useValues } from 'kea'
import { dashboardLogic, DashboardLogicProps } from 'scenes/dashboard/dashboardLogic'
import { DashboardItems } from 'scenes/dashboard/DashboardItems'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CalendarOutlined } from '@ant-design/icons'
import './Dashboard.scss'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { DashboardPlacement, DashboardMode } from '~/types'
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
    placement?: DashboardPlacement
}

export const scene: SceneExport = {
    component: Dashboard,
    logic: dashboardLogic,
    paramsToProps: ({ params: { id } }): DashboardLogicProps => ({ id: parseInt(id) }),
}

export function Dashboard({ id, shareToken, placement }: Props = {}): JSX.Element {
    return (
        <BindLogic logic={dashboardLogic} props={{ id: id ? parseInt(id) : undefined, shareToken }}>
            <DashboardView placement={placement} />
        </BindLogic>
    )
}

function DashboardView({ placement }: Pick<Props, 'placement'>): JSX.Element {
    const {
        dashboard,
        canEditDashboard,
        allItemsLoading,
        items,
        filters: dashboardFilters,
        dashboardMode,
        receivedErrorsFromAPI,
    } = useValues(dashboardLogic)
    const { setDashboardMode, setDates, reportDashboardViewed } = useActions(dashboardLogic)

    useEffect(() => {
        reportDashboardViewed()
    }, [])

    useKeyboardHotkeys(
        placement === DashboardPlacement.Public || placement === DashboardPlacement.InternalMetrics
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

    if (!dashboard && !allItemsLoading) {
        return <NotFound object="dashboard" />
    }

    return (
        <div className="dashboard">
            {placement !== DashboardPlacement.ProjectHomepage &&
                placement !== DashboardPlacement.Public &&
                placement !== DashboardPlacement.InternalMetrics && <DashboardHeader />}

            {receivedErrorsFromAPI ? (
                <InsightErrorState title="There was an error loading this dashboard" />
            ) : !items || items.length === 0 ? (
                <EmptyDashboardComponent loading={allItemsLoading} />
            ) : (
                <div>
                    <div className="dashboard-items-actions">
                        <div
                            className="left-item"
                            style={placement === DashboardPlacement.Public ? { textAlign: 'right' } : undefined}
                        >
                            {placement === DashboardPlacement.Public ? <LastRefreshText /> : <DashboardReloadAction />}
                        </div>

                        {placement !== DashboardPlacement.Public && (
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
