import React from 'react'
import { SceneLoading } from 'lib/utils'
import { BindLogic, useActions, useValues } from 'kea'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { DashboardHeader } from 'scenes/dashboard/DashboardHeader'
import { DashboardItems } from 'scenes/dashboard/DashboardItems'
import { dashboardsModel } from '~/models/dashboardsModel'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CalendarOutlined } from '@ant-design/icons'
import './Dashboard.scss'
import { useKeyboardHotkeys } from '../../lib/hooks/useKeyboardHotkeys'
import { DashboardMode } from '../../types'
import { DashboardEventSource } from '../../lib/utils/eventUsageLogic'
import { TZIndicator } from 'lib/components/TimezoneAware'
import { Link } from 'lib/components/Link'
import { EmptyDashboardComponent } from './EmptyDashboardComponent'

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
    const { dashboard, itemsLoading, items, filters: dashboardFilters, dashboardMode } = useValues(dashboardLogic)
    const { dashboardsLoading } = useValues(dashboardsModel)
    const { setDashboardMode, addGraph, setDates } = useActions(dashboardLogic)

    useKeyboardHotkeys(
        dashboardMode === DashboardMode.Public
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
                  s: {
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
        return (
            <div className="dashboard not-found">
                <div className="graphic" />
                <h1 className="page-title">Dashboard not found</h1>
                <b>It seems this page may have been lost in space.</b>
                <p>
                    It’s possible this dashboard may have been deleted or its sharing settings changed. Please check
                    with the person who sent you here, or{' '}
                    <Link
                        to="https://posthog.com/support?utm_medium=in-product&utm_campaign=dashboard-not-found"
                        target="_blank"
                        rel="noopener"
                    >
                        contact support
                    </Link>{' '}
                    if you think this is a mistake
                </p>
            </div>
        )
    }

    return (
        <div className="dashboard">
            {dashboardMode !== DashboardMode.Public && <DashboardHeader />}
            {items && items.length ? (
                <div>
                    <div className="dashboard-items-actions">
                        {/* :TODO: Bring this back when addressing https://github.com/PostHog/posthog/issues/3609
                        <div className="left-item">
                            Last updated <b>{lastRefreshed ? dayjs(lastRefreshed).fromNow() : 'a while ago'}</b>
                            {dashboardMode !== DashboardMode.Public && (
                                <Button type="link" icon={<ReloadOutlined />} onClick={refreshAllDashboardItems}>
                                    Refresh
                                </Button>
                            )}
                        </div>
                         */}
                        {dashboardMode !== DashboardMode.Public && (
                            <div
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'flex-end',
                                    width: '100%',
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
                    <DashboardItems inSharedMode={dashboardMode === DashboardMode.Public} />
                </div>
            ) : (
                <EmptyDashboardComponent />
            )}
        </div>
    )
}
