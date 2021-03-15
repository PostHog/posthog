import React from 'react'
import { SceneLoading } from 'lib/utils'
import { BindLogic, useActions, useValues } from 'kea'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { DashboardHeader } from 'scenes/dashboard/DashboardHeader'
import { DashboardItems } from 'scenes/dashboard/DashboardItems'
import { dashboardsModel } from '~/models/dashboardsModel'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CalendarOutlined, ReloadOutlined } from '@ant-design/icons'
import moment from 'moment'
import { Button } from 'antd'
import './Dashboard.scss'
import { useKeyboardHotkeys } from '../../lib/hooks/useKeyboardHotkeys'

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

    const HOTKEYS =
        dashboardMode === 'public'
            ? {}
            : {
                  e: {
                      action: () => setDashboardMode(dashboardMode === 'edit' ? null : 'edit', 'hotkey'),
                      disabled: dashboardMode !== null && dashboardMode !== 'edit',
                  },
                  f: {
                      action: () => setDashboardMode(dashboardMode === 'fullscreen' ? null : 'fullscreen', 'hotkey'),
                      disabled: dashboardMode !== null && dashboardMode !== 'fullscreen',
                  },
                  s: {
                      action: () => setDashboardMode(dashboardMode === 'sharing' ? null : 'sharing', 'hotkey'),
                      disabled: dashboardMode !== null && dashboardMode !== 'sharing',
                  },
                  n: {
                      action: () => addGraph(),
                      disabled: dashboardMode !== null && dashboardMode !== 'edit',
                  },
                  escape: {
                      // Exit edit mode with Esc. Full screen mode is also exited with Esc, but this behavior is native to the browser.
                      action: () => setDashboardMode(null, 'hotkey'),
                      disabled: dashboardMode !== 'edit',
                  },
              }

    useKeyboardHotkeys(HOTKEYS)

    if (dashboardsLoading || itemsLoading) {
        return <SceneLoading />
    }

    if (!dashboard) {
        return (
            <>
                <p>Dashboard not found.</p>
            </>
        )
    }

    return (
        <div className="dashboard">
            {dashboardMode !== 'public' && <DashboardHeader />}
            {items && items.length ? (
                <div>
                    <div className="dashboard-items-actions">
                        <div className="left-item">
                            Last updated <b>{lastRefreshed ? moment(lastRefreshed).fromNow() : 'a while ago'}</b>
                            <Button type="link" icon={<ReloadOutlined />} onClick={refreshAllDashboardItems}>
                                Refresh
                            </Button>
                        </div>
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
                    <DashboardItems inSharedMode={dashboardMode === 'public'} />
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
