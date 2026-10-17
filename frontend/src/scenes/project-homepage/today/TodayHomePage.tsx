import { useValues } from 'kea'

import { Skeleton, Text } from '@posthog/quill'

import { TodayExplore } from './TodayExplore'
import { TodayForYou } from './TodayForYou'
import { todayHighlightsLogic } from './todayHighlightsLogic'
import { todayLogic } from './todayLogic'
import { TodayPulse } from './TodayPulse'
import { TodayRecents } from './TodayRecents'
import { TodaySampleBanner } from './TodaySampleBanner'

const DATE_FORMAT = new Intl.DateTimeFormat(undefined, { weekday: 'long', day: 'numeric', month: 'long' })

function TodayPulseSkeleton(): JSX.Element {
    return (
        <ul className="TodayPulse" aria-busy aria-label="Loading key numbers">
            {['w-14', 'w-16', 'w-20'].map((width) => (
                <li key={width} className="TodayPulse__metric">
                    <span className="TodayPulse__name">
                        <Skeleton className={`inline-block h-3 align-middle ${width}`} />
                    </span>
                    <span className="TodayPulse__row">
                        <span className="TodayPulse__value">
                            <Skeleton className="inline-block h-4 w-28 align-middle" />
                        </span>
                    </span>
                </li>
            ))}
        </ul>
    )
}

function TodayMetaLine(): JSX.Element {
    const { now } = useValues(todayLogic)
    const date = new Date(now)
    return (
        <p className="TodayHome__meta">
            <time translate="no" dateTime={date.toISOString()}>
                {DATE_FORMAT.format(date)}
            </time>
        </p>
    )
}

export function TodayHomePage(): JSX.Element {
    const { greeting, isNewProject, recentObjects } = useValues(todayLogic)
    const { highlights, highlightsPending } = useValues(todayHighlightsLogic)

    return (
        <div className="TodayHome Today__page" data-quill>
            <TodaySampleBanner />
            <section className="TodayHome__intro" aria-label="Today">
                <div className="TodayHome__greeting">
                    <Text render={<h1 />} className="m-0 text-[21px] font-[560] tracking-[-0.015em]">
                        {greeting}
                    </Text>
                </div>
                <TodayMetaLine />
            </section>
            <div className="TodayHome__body">
                {highlightsPending ? (
                    <TodayPulseSkeleton />
                ) : highlights && highlights.pulse.length > 0 ? (
                    <TodayPulse metrics={highlights.pulse} />
                ) : null}
                {isNewProject && recentObjects.length === 0 ? <TodayExplore /> : <TodayRecents />}
                <TodayForYou />
            </div>
        </div>
    )
}
