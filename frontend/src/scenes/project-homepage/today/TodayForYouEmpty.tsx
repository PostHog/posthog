import './Today.scss'

import { useValues } from 'kea'
import { Suspense } from 'react'

import { IconCheckCircle } from '@posthog/icons'
import { Button, IconStack, IconStackItem, Skeleton } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { urls } from 'scenes/urls'

import { TodayAiRow } from './TodayAiRow'
import { todayLogic } from './todayLogic'
import { todayPromptsLogic } from './todayPromptsLogic'
import { TodayWatchedNote } from './TodayWatchedNote'

const TodaySelfDrivingStatus = lazyWithRetry(() =>
    import('./TodaySelfDrivingStatus').then(({ TodaySelfDrivingStatus }) => ({ default: TodaySelfDrivingStatus }))
)

const ALERTS_CTA = { label: 'Set up alerts', to: urls.alerts(), dataAttr: 'today-for-you-empty-alerts' }
const SELF_DRIVING_CTA = {
    label: 'Set up self-driving',
    to: urls.inbox(),
    dataAttr: 'today-for-you-empty-self-driving',
}

function localDayNumber(now: number): number {
    const date = new Date(now)
    return Math.floor(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / 86_400_000)
}

function QuietRow({ offerSelfDriving }: { offerSelfDriving: boolean }): JSX.Element {
    const { now } = useValues(todayLogic)
    const cta = offerSelfDriving && localDayNumber(now) % 2 === 1 ? SELF_DRIVING_CTA : ALERTS_CTA
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
                        render={<LinkPrimitive to={cta.to} />}
                        data-attr={cta.dataAttr}
                    >
                        {cta.label}
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
                <QuietRow offerSelfDriving={false} />
            </>
        )
    }
    return (
        <Suspense fallback={<Skeleton className="h-12 w-full" />}>
            <TodaySelfDrivingStatus quietRow={(offerSelfDriving) => <QuietRow offerSelfDriving={offerSelfDriving} />} />
        </Suspense>
    )
}
