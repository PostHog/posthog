import { useValues } from 'kea'
import { useId } from 'react'

import { IconDashboard } from '@posthog/icons'
import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { DashboardPlacement } from '~/types'

import { TodayHomeHeading } from './TodayHomeHeading'
import { todayLogic } from './todayLogic'
import { TodayPrimaryDashboardPicker } from './TodayPrimaryDashboardPicker'

/** A cropped, non-interactive preview of the project's primary dashboard; the whole preview opens the dashboard. Hidden outside edit mode when none is set. */
export function TodayPrimaryDashboard(): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const { homeEditing } = useValues(todayLogic)
    const titleId = useId()
    const dashboardId = currentTeam?.primary_dashboard ?? null
    if (!dashboardId && !homeEditing) {
        return null
    }

    return (
        <section className="TodayHome__list" aria-labelledby={titleId}>
            <div className="TodayHome__headingRow">
                <TodayHomeHeading id={titleId}>Primary dashboard</TodayHomeHeading>
                {homeEditing ? (
                    <TodayPrimaryDashboardPicker
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
                    {/* `inert` keeps the tiles' own links and menus out of the tab order; React 18 types lack the attribute.
                        The filter bar is hidden with a Tailwind variant because its `flex` utility outranks Today.scss. */}
                    <div
                        className="TodayPrimaryDashboard__preview [&_.scene-sticky-bar]:hidden"
                        aria-hidden
                        {...{ inert: '' }}
                    >
                        <Dashboard
                            id={String(dashboardId)}
                            placement={DashboardPlacement.ProjectHomepage}
                            readOnly
                            recordsView={false}
                        />
                    </div>
                    <LinkPrimitive
                        to={urls.dashboard(dashboardId)}
                        className="TodayPrimaryDashboard__link"
                        aria-label="Open primary dashboard"
                        data-attr="today-home-primary-dashboard-open"
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
