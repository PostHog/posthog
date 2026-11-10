import { useValues } from 'kea'

import { IconCheckCircle } from '@posthog/icons'
import { Button, IconStack, IconStackItem } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { TodayAiRow } from './TodayAiRow'
import { todayPromptsLogic } from './todayPromptsLogic'
import { TodaySelfDrivingStatus } from './TodaySelfDrivingStatus'
import { TodayWatchedNote } from './TodayWatchedNote'

function QuietRow(): JSX.Element {
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
                    <TodayWatchedNote text="Checks each day: alerts, experiments, flags, workflows and tickets." />
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

export function TodayForYouEmpty(): JSX.Element {
    const { aiEnabled } = useValues(todayPromptsLogic)

    if (!aiEnabled) {
        return (
            <>
                <TodayAiRow />
                <QuietRow />
            </>
        )
    }
    return <TodaySelfDrivingStatus fallback={<QuietRow />} />
}
