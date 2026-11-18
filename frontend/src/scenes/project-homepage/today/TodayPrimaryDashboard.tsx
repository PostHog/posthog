import './Today.scss'

import { useActions, useValues } from 'kea'
import { Suspense, useId } from 'react'

import { IconDashboard } from '@posthog/icons'
import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { urls } from 'scenes/urls'

import { DashboardPlacement } from '~/types'

import { todayHomeEditLogic } from './todayHomeEditLogic'
import { TodayHomeHeading } from './TodayHomeHeading'
import { todayPrimaryDashboardLogic } from './todayPrimaryDashboardLogic'
import { TodayPrimaryDashboardPicker } from './TodayPrimaryDashboardPicker'

// Only projects with a primary dashboard need the dashboard scene, so it loads in its own chunk rather than with Home.
const Dashboard = lazyWithRetry(() => import('scenes/dashboard/Dashboard').then((m) => ({ default: m.Dashboard })))

export function TodayPrimaryDashboard(): JSX.Element | null {
    const { homeEditing } = useValues(todayHomeEditLogic)
    const { primaryDashboardId: dashboardId, useSampleData } = useValues(todayPrimaryDashboardLogic)
    const { primaryDashboardOpened } = useActions(todayPrimaryDashboardLogic)
    const titleId = useId()
    if (useSampleData || (!dashboardId && !homeEditing)) {
        return null
    }

    return (
        <section className="TodayHome__list" aria-labelledby={titleId}>
            <div className="TodayHome__headingRow">
                <TodayHomeHeading id={titleId}>Primary dashboard</TodayHomeHeading>
                {homeEditing ? (
                    <TodayPrimaryDashboardPicker
                        source="edit"
                        trigger={
                            <Button
                                variant="outline"
                                size="sm"
                                className="-my-1"
                                aria-label={dashboardId ? 'Change primary dashboard' : 'Choose primary dashboard'}
                                data-attr="today-home-primary-dashboard-edit"
                            >
                                Edit
                            </Button>
                        }
                    />
                ) : null}
            </div>
            {dashboardId ? (
                <div className="TodayPrimaryDashboard">
                    {/* `inert` keeps the tiles' own links and menus out of the tab order; React 18 types lack the attribute */}
                    <div className="TodayPrimaryDashboard__preview" aria-hidden {...{ inert: '' }}>
                        <Suspense fallback={null}>
                            <Dashboard id={String(dashboardId)} placement={DashboardPlacement.ProjectHomepage} />
                        </Suspense>
                    </div>
                    <LinkPrimitive
                        to={urls.dashboard(dashboardId)}
                        className="TodayPrimaryDashboard__link"
                        aria-label="Open primary dashboard"
                        data-attr="today-home-primary-dashboard-open"
                        onClick={() => primaryDashboardOpened(dashboardId)}
                    >
                        <span className="TodayPrimaryDashboard__cta">Open dashboard</span>
                    </LinkPrimitive>
                </div>
            ) : (
                <Empty className="border border-dashed">
                    <EmptyHeader>
                        <EmptyMedia variant="icon">
                            <IconDashboard />
                        </EmptyMedia>
                        <EmptyTitle>No primary dashboard</EmptyTitle>
                        <EmptyDescription>
                            Choose a dashboard to show here for everyone in this project.
                        </EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                        <TodayPrimaryDashboardPicker
                            source="empty"
                            trigger={
                                <Button variant="primary" size="sm" data-attr="today-home-primary-dashboard-choose">
                                    Choose dashboard
                                </Button>
                            }
                        />
                    </EmptyContent>
                </Empty>
            )}
        </section>
    )
}
