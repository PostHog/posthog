import React from 'react'
import { SceneLoading } from 'lib/utils'
import { BindLogic, useActions, useValues } from 'kea'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { DashboardHeader } from 'scenes/dashboard/DashboardHeader'
import { DashboardItems } from 'scenes/dashboard/DashboardItems'
import { dashboardsModel } from '~/models/dashboardsModel'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CalendarOutlined, ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { Button } from 'antd'
import './Dashboard.scss'
import { useKeyboardHotkeys } from '../../lib/hooks/useKeyboardHotkeys'
import { DashboardMode } from '../../types'
import { EventSource } from '../../lib/utils/eventUsageLogic'
import { TZIndicator } from 'lib/components/TimezoneAware'

interface Props {
    id: string
    shareToken?: string
}

export function Dashboard({ id, shareToken }: Props): JSX.Element {
    return (
        <BindLogic logic={dashboardLogic} props={{ id: parseInt(id), shareToken }}>
            <DashboardView />
        </BindLogic>
    )
}

function DashboardView(): JSX.Element {
    const { dashboard, itemsLoading, items, lastRefreshed, filters: dashboardFilters, dashboardMode } = useValues(
        dashboardLogic
    )
    const { dashboardsLoading } = useValues(dashboardsModel)
    const { refreshAllDashboardItems, setDashboardMode, addGraph, setDates } = useActions(dashboardLogic)

    useKeyboardHotkeys(
        dashboardMode === DashboardMode.Public
            ? {}
            : {
                  e: {
                      action: () =>
                          setDashboardMode(
                              dashboardMode === DashboardMode.Edit ? null : DashboardMode.Edit,
                              EventSource.Hotkey
                          ),
                      disabled: dashboardMode !== null && dashboardMode !== DashboardMode.Edit,
                  },
                  f: {
                      action: () =>
                          setDashboardMode(
                              dashboardMode === DashboardMode.Fullscreen ? null : DashboardMode.Fullscreen,
                              EventSource.Hotkey
                          ),
                      disabled: dashboardMode !== null && dashboardMode !== DashboardMode.Fullscreen,
                  },
                  s: {
                      action: () =>
                          setDashboardMode(
                              dashboardMode === DashboardMode.Sharing ? null : DashboardMode.Sharing,
                              EventSource.Hotkey
                          ),
                      disabled: dashboardMode !== null && dashboardMode !== DashboardMode.Sharing,
                  },
                  n: {
                      action: () => addGraph(),
                      disabled: dashboardMode !== null && dashboardMode !== DashboardMode.Edit,
                  },
                  escape: {
                      // Exit edit mode with Esc. Full screen mode is also exited with Esc, but this behavior is native to the browser.
                      action: () => setDashboardMode(null, EventSource.Hotkey),
                      disabled: dashboardMode !== DashboardMode.Edit,
                  },
              },
        [setDashboardMode, dashboardMode]
    )

    if (dashboardsLoading || itemsLoading) {
        return <SceneLoading />
    }

    if (!dashboard) {
        return <p>Dashboard not found.</p>
    }

    return (
        <div className="dashboard">
            {dashboardMode !== 'public' && <DashboardHeader />}
            {items && items.length ? (
                <div>
                    <div className="dashboard-items-actions">
                        <div className="left-item">
                            <TZIndicator style={{ marginRight: 8, fontWeight: 'bold' }} />
                            Last updated <b>{lastRefreshed ? dayjs(lastRefreshed).fromNow() : 'a while ago'}</b>
                            {dashboardMode !== DashboardMode.Public && (
                                <Button type="link" icon={<ReloadOutlined />} onClick={refreshAllDashboardItems}>
                                    Refresh
                                </Button>
                            )}
                        </div>
                        {dashboardMode !== DashboardMode.Public && (
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
                        )}
                    </div>
                    <DashboardItems inSharedMode={dashboardMode === DashboardMode.Public} />
                </div>
            ) : (
                <p>
                    There are no panels on this dashboard.{' '}
                    <Button type="link" onClick={addGraph}>
                        Click here to add some!
                    </Button>
                </p>
            )}
        </div>
    )
}
