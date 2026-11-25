import './Today.scss'

import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { IconArrowRight, IconDashboard } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Skeleton,
} from '@posthog/quill'

import { LazyLemonMarkdown } from 'lib/lemon-ui/LemonMarkdown/LazyLemonMarkdown'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { TodayObjectIcon } from '~/layout/today/TodayObjectIcon'

import { todayHomeEditLogic } from './todayHomeEditLogic'
import { TodayHomeHeading } from './TodayHomeHeading'
import { todayPrimaryDashboardLogic } from './todayPrimaryDashboardLogic'
import { TodayPrimaryDashboardPicker } from './TodayPrimaryDashboardPicker'

export function TodayPrimaryDashboard(): JSX.Element | null {
    const { homeEditing } = useValues(todayHomeEditLogic)
    const { primaryDashboardId, primaryDashboard, primaryDashboardLoading, useSampleData } =
        useValues(todayPrimaryDashboardLogic)
    const { primaryDashboardOpened } = useActions(todayPrimaryDashboardLogic)
    const titleId = useId()
    if (useSampleData || (!primaryDashboardLoading && !primaryDashboard && !homeEditing)) {
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
                                aria-label={
                                    primaryDashboardId ? 'Change primary dashboard' : 'Choose primary dashboard'
                                }
                                data-attr="today-home-primary-dashboard-edit"
                            >
                                Edit
                            </Button>
                        }
                    />
                ) : null}
            </div>
            {primaryDashboardLoading ? (
                <div className="TodayRow TodayPrimaryDashboard" aria-busy aria-label="Loading">
                    <Skeleton className="TodayRow__iconSkeleton" />
                    <div className="flex flex-col gap-2 py-1">
                        <Skeleton className="h-3.5 w-2/5" />
                        <Skeleton className="h-3 w-3/5" />
                    </div>
                </div>
            ) : primaryDashboard ? (
                <div className="TodayRow TodayPrimaryDashboard" data-interactive>
                    <TodayObjectIcon type="dashboard" className="TodayRow__icons" />
                    <div className="min-w-0">
                        <LinkPrimitive
                            to={urls.dashboard(primaryDashboard.id)}
                            className="TodayRow__title TodayRow__link"
                            data-attr="today-home-primary-dashboard-row"
                            onClick={() => primaryDashboardOpened(primaryDashboard.id)}
                        >
                            {primaryDashboard.name || 'Untitled dashboard'}
                        </LinkPrimitive>
                        {primaryDashboard.description ? (
                            // Links and images stay inert, because the whole row already opens the dashboard
                            <LazyLemonMarkdown
                                className="TodayRow__meta TodayPrimaryDashboard__description"
                                lowKeyHeadings
                                disableLinks
                                disableImages="all"
                            >
                                {primaryDashboard.description}
                            </LazyLemonMarkdown>
                        ) : null}
                    </div>
                    <div className="TodayRow__end">
                        <IconArrowRight className="TodayRow__arrow" aria-hidden />
                    </div>
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
