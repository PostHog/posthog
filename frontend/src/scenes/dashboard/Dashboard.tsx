import React from 'react'
import dayjs from 'dayjs'
import { SceneLoading } from 'lib/utils'
import { BindLogic, useActions, useValues } from 'kea'
import { AUTO_REFRESH_INTERVAL_MINS, dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { DashboardHeader } from 'scenes/dashboard/DashboardHeader'
import { DashboardItems } from 'scenes/dashboard/DashboardItems'
import { dashboardsModel } from '~/models/dashboardsModel'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CalendarOutlined, ReloadOutlined } from '@ant-design/icons'
import './Dashboard.scss'
import { useKeyboardHotkeys } from '../../lib/hooks/useKeyboardHotkeys'
import { DashboardMode } from '../../types'
import { DashboardEventSource } from '../../lib/utils/eventUsageLogic'
import { TZIndicator } from 'lib/components/TimezoneAware'
import { EmptyDashboardComponent } from './EmptyDashboardComponent'
import { NotFound } from 'lib/components/NotFound'
import { Button, Row, Switch, Tooltip } from 'antd'

interface Props {
    id: string
    shareToken?: string
    internal?: boolean
}

export function Dashboard({ id, shareToken, internal }: Props): JSX.Element {
    return (
        <BindLogic logic={dashboardLogic} props={{ id: parseInt(id), shareToken, internal }}>
            <DashboardView />
        </BindLogic>
    )
}

function DashboardView(): JSX.Element {
    const {
        dashboard,
        itemsLoading,
        items,
        filters: dashboardFilters,
        dashboardMode,
        lastRefreshed,
        autoRefresh,
        refreshStatus,
    } = useValues(dashboardLogic)
    const { dashboardsLoading } = useValues(dashboardsModel)
    const { setDashboardMode, addGraph, setDates, refreshAllDashboardItems, setAutoRefresh } = useActions(
        dashboardLogic
    )

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
                      disabled: dashboardMode !== null && dashboardMode !== DashboardMode.Edit,
                  },
                  f: {
                      action: () =>
                          setDashboardMode(
                              dashboardMode === DashboardMode.Fullscreen ? null : DashboardMode.Fullscreen,
                              DashboardEventSource.Hotkey
                          ),
                      disabled: dashboardMode !== null && dashboardMode !== DashboardMode.Fullscreen,
                  },
                  k: {
                      action: () =>
                          setDashboardMode(
                              dashboardMode === DashboardMode.Sharing ? null : DashboardMode.Sharing,
                              DashboardEventSource.Hotkey
                          ),
                      disabled: dashboardMode !== null && dashboardMode !== DashboardMode.Sharing,
                  },
                  n: {
                      action: () => addGraph(),
                      disabled: dashboardMode !== null && dashboardMode !== DashboardMode.Edit,
                  },
                  escape: {
                      // Exit edit mode with Esc. Full screen mode is also exited with Esc, but this behavior is native to the browser.
                      action: () => setDashboardMode(null, DashboardEventSource.Hotkey),
                      disabled: dashboardMode !== DashboardMode.Edit,
                  },
              },
        [setDashboardMode, dashboardMode]
    )

    if (dashboardsLoading || itemsLoading) {
        return <SceneLoading />
    }

    if (!dashboard) {
        return <NotFound object="dashboard" />
    }

    console.log('REfresh status', refreshStatus, items)

    return (
        <div className="dashboard">
            {dashboardMode !== DashboardMode.Public && dashboardMode !== DashboardMode.Internal && <DashboardHeader />}
            {items && items.length ? (
                <div>
                    <div className="dashboard-items-actions">
                        <div className="left-item">
                            Last updated <b>{lastRefreshed ? dayjs(lastRefreshed).fromNow() : 'a while ago'}</b>
                            {dashboardMode !== DashboardMode.Public && (
                                <>
                                    <Button
                                        type="link"
                                        icon={<ReloadOutlined />}
                                        onClick={() => refreshAllDashboardItems()}
                                    >
                                        Refresh
                                    </Button>
                                    <Tooltip
                                        title={`Refresh dashboard automatically every ${AUTO_REFRESH_INTERVAL_MINS} minutes`}
                                        placement="bottomLeft"
                                    >
                                        <Row style={{ alignItems: 'center', flexWrap: 'nowrap' }}>
                                            <Switch
                                                // @ts-expect-error `id` prop is valid on switch
                                                id="auto-refresh"
                                                onChange={setAutoRefresh}
                                                checked={autoRefresh}
                                                size="small"
                                            />
                                            <label
                                                style={{
                                                    marginLeft: 10,
                                                }}
                                                htmlFor="auto-refresh"
                                            >
                                                Auto refresh
                                            </label>
                                        </Row>
                                    </Tooltip>
                                </>
                            )}
                        </div>

                        {dashboardMode !== DashboardMode.Public && (
                            <div
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
                                    dateFrom={dashboardFilters?.date_from}
                                    dateTo={dashboardFilters?.date_to}
                                    onChange={setDates}
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
            ) : (
                <EmptyDashboardComponent />
            )}
        </div>
    )
}
