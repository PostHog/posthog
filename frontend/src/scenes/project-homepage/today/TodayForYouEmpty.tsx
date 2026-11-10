import { useValues } from 'kea'

import { IconCheckCircle } from '@posthog/icons'
import { Button, IconStack, IconStackItem, Skeleton, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { todayGetStartedLogic } from './todayGetStartedLogic'
import { TodaySetupRow } from './TodaySetupRow'

export function TodayForYouEmpty(): JSX.Element {
    const { stepsReady, allDone, hidden } = useValues(todayGetStartedLogic)
    const showGuide = !allDone && !hidden

    if (!stepsReady && !hidden) {
        return <Skeleton className="h-12 w-full" />
    }
    if (showGuide) {
        return (
            <>
                <TodaySetupRow />
                <Text size="xs" variant="muted" render={<p />} className="m-0">
                    Nothing else needs you today.
                </Text>
            </>
        )
    }
    return (
        <ol className="TodayRows" data-attr="today-for-you-empty">
            <li className="TodayRow">
                <IconStack className="TodayRow__icons">
                    <IconStackItem color="var(--success-foreground)">
                        <IconCheckCircle />
                    </IconStackItem>
                </IconStack>
                <div className="min-w-0">
                    <span className="TodayRow__title">Nothing needs you today</span>
                    <p className="TodayRow__meta">
                        PostHog checks your alerts, experiments, flags and tickets each day.
                    </p>
                </div>
                <div className="TodayRow__end">
                    <Button
                        size="sm"
                        variant="link-muted"
                        render={<LinkPrimitive to={urls.alerts()} />}
                        data-attr="today-for-you-empty-alerts"
                    >
                        Set up alerts
                    </Button>
                </div>
            </li>
        </ol>
    )
}
