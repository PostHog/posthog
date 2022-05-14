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
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'

interface Props {
    id?: string
    shareToken?: string
    placement?: DashboardPlacement
}

export const scene: SceneExport = {
    component: DashboardScene,
    logic: dashboardLogic,
    paramsToProps: ({ params: { id, shareToken, placement } }: { params: Props }): DashboardLogicProps => ({
        id: id ? parseInt(id) : undefined,
        shareToken,
        placement,
    }),
}

export function Dashboard({ id, shareToken, placement }: Props = {}): JSX.Element {
    return (
        <BindLogic logic={dashboardLogic} props={{ id: id ? parseInt(id) : undefined, shareToken, placement }}>
            <DashboardScene />
        </BindLogic>
    )
}

function DashboardScene(): JSX.Element {
    const {
        placement,
        dashboard,
        canEditDashboard,
        items,
        itemsLoading,
        filters: dashboardFilters,
        dashboardMode,
        receivedErrorsFromAPI,
    } = useValues(dashboardLogic)
    const { setDashboardMode, setDates, reportDashboardViewed, setProperties } = useActions(dashboardLogic)

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

    if (!dashboard && !itemsLoading && receivedErrorsFromAPI) {
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
                <EmptyDashboardComponent loading={itemsLoading} />
            ) : (
                <div>
                    {placement !== DashboardPlacement.Public && (
                        <div className="flex pb space-x">
                            <TZIndicator style={{ marginRight: 8, fontWeight: 'bold', lineHeight: '30px' }} />
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
                            <PropertyFilters
                                onChange={setProperties}
                                pageKey={'dashboard_' + dashboard?.id}
                                propertyFilters={dashboard?.filters.properties}
                                useLemonButton
                            />
                        </div>
                    )}
                    <div className="flex pt pb border-top space-x dashoard-items-actions">
                        <div
                            className="left-item"
                            style={placement === DashboardPlacement.Public ? { textAlign: 'right' } : undefined}
                        >
                            {placement === DashboardPlacement.Public ? <LastRefreshText /> : <DashboardReloadAction />}
                        </div>
                    </div>
                    <DashboardItems />
                </div>
            )}
        </div>
    )
}
