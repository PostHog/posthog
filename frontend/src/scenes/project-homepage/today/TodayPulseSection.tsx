import { useValues } from 'kea'
import { useId } from 'react'

import { Skeleton, Text } from '@posthog/quill'

import type { HighlightsApi, PulseSlotApi } from 'products/today/frontend/generated/api.schemas'

import { todayHighlightsLogic } from './todayHighlightsLogic'
import { TodayHomeHeading } from './TodayHomeHeading'
import { TodayPulse } from './TodayPulse'
import { TodayPulseEditor } from './TodayPulseEditor'

function TodayPulseSkeleton(): JSX.Element {
    return (
        <ul className="TodayPulse" aria-busy aria-label="Loading key numbers">
            {['w-14', 'w-20', 'w-16', 'w-24'].map((width) => (
                <li key={width} className="TodayPulse__metric">
                    <span className="TodayPulse__name">
                        <Skeleton className={`inline-block h-3 align-middle ${width}`} />
                    </span>
                    <span className="TodayPulse__row">
                        <span className="TodayPulse__value">
                            <Skeleton className="inline-block h-4 w-28 align-middle" />
                        </span>
                    </span>
                    <span className="TodayPulse__spark">
                        <Skeleton className="h-3 w-full" />
                    </span>
                </li>
            ))}
        </ul>
    )
}

type PulseView = 'loading' | 'numbers' | 'empty' | null

function pulseView(
    pulsePending: boolean,
    highlights: HighlightsApi | null,
    pulseSlots: PulseSlotApi[] | undefined
): PulseView {
    if (pulsePending) {
        return 'loading'
    }
    if (highlights && pulseSlots && pulseSlots.length > 0) {
        return 'numbers'
    }
    return highlights?.status === 'ready' ? 'empty' : null
}

export function TodayPulseSection(): JSX.Element | null {
    const { highlights, pulsePending, pulseTiles, pulseSlots, pulsePinsLoaded } = useValues(todayHighlightsLogic)
    const titleId = useId()
    const view = pulseView(pulsePending, highlights, pulseSlots)
    const canEdit = !pulsePending && !!highlights && pulsePinsLoaded
    if (view === null && !canEdit) {
        return null
    }
    return (
        <section className="TodayHome__list" aria-labelledby={titleId}>
            <div className="TodayHome__headingRow">
                <TodayHomeHeading id={titleId}>At a glance</TodayHomeHeading>
                {canEdit ? <TodayPulseEditor /> : null}
            </div>
            {view === 'loading' ? <TodayPulseSkeleton /> : null}
            {view === 'numbers' ? <TodayPulse metrics={pulseTiles} slots={pulseSlots} /> : null}
            {view === 'empty' ? (
                <Text size="sm" variant="muted" render={<p />} className="m-0">
                    Key numbers show here when you or your team open a few trend insights.
                </Text>
            ) : null}
        </section>
    )
}
