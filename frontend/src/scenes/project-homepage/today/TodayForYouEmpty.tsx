import { useValues } from 'kea'

import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    IconStack,
    IconStackItem,
    Skeleton,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { TodayGetStarted } from './TodayGetStarted'
import { todayGetStartedLogic } from './todayGetStartedLogic'
import { WATCHED_PRODUCT_ICONS } from './todayRowIcons'

export function TodayForYouEmpty(): JSX.Element {
    const { stepsReady, allDone, hidden } = useValues(todayGetStartedLogic)

    if (!stepsReady && !hidden) {
        return <Skeleton className="h-40 w-full" />
    }
    if (!allDone && !hidden) {
        return <TodayGetStarted />
    }
    return (
        <Empty className="TodayEmpty" data-attr="today-for-you-empty">
            <EmptyHeader>
                <IconStack>
                    {WATCHED_PRODUCT_ICONS.map((icon, index) => (
                        <IconStackItem key={index} color={icon.color}>
                            {icon.glyph}
                        </IconStackItem>
                    ))}
                </IconStack>
                <EmptyTitle>Nothing needs you today</EmptyTitle>
                <EmptyDescription>
                    Each day, PostHog checks your alerts, experiments, feature flags, workflows, support tickets and
                    recordings. When something changes that needs you, it shows up here.
                </EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
                <Button
                    size="sm"
                    variant="outline"
                    render={<LinkPrimitive to={urls.alerts()} />}
                    data-attr="today-for-you-empty-alerts"
                >
                    Set up alerts
                </Button>
            </EmptyContent>
        </Empty>
    )
}
