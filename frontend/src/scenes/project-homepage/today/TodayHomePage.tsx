import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useLayoutEffect, useRef } from 'react'

import { Skeleton, Text, cn } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { TodayExplore } from './TodayExplore'
import { TodayForYou } from './TodayForYou'
import { todayHighlightsLogic } from './todayHighlightsLogic'
import { TodayHomeComposer } from './TodayHomeComposer'
import { reportIdFromPath, todayLogic } from './todayLogic'
import { TodayNewsButton } from './TodayNewsButton'
import { TodayNewsDialog } from './TodayNewsDialog'
import { TodayPulse } from './TodayPulse'
import { TodayPulseEditor } from './TodayPulseEditor'
import { TodayRecents } from './TodayRecents'
import { TodaySampleBanner } from './TodaySampleBanner'

const DATE_FORMAT = new Intl.DateTimeFormat(undefined, { weekday: 'long', day: 'numeric', month: 'long' })

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
    const { greeting, isNewProject, recentObjects, returnFocusReportId, useSampleData } = useValues(todayLogic)
    const { setReturnFocusReportId } = useActions(todayLogic)
    const {
        currentProjectId,
        highlights,
        highlightsLoading,
        highlightsFailed,
        highlightsPending,
        pulsePending,
        pulseTiles,
        pulseSlots,
        pulsePinsLoaded,
    } = useValues(todayHighlightsLogic)
    const { pulseViewMounted, pulseViewUpdated, pulseViewUnmounted } = useActions(todayHighlightsLogic)
    const rootRef = useRef<HTMLDivElement>(null)
    const todayNews = useFeatureFlag('TODAY_NEWS')

    useLayoutEffect(() => {
        pulseViewMounted(useSampleData)
        return () => pulseViewUnmounted()
    }, [currentProjectId, useSampleData, pulseViewMounted, pulseViewUnmounted])

    useLayoutEffect(() => {
        pulseViewUpdated()
    }, [
        highlights,
        highlightsLoading,
        highlightsFailed,
        highlightsPending,
        pulsePending,
        pulseTiles,
        pulseSlots,
        pulseViewUpdated,
        currentProjectId,
        useSampleData,
    ])

    useLayoutEffect(() => {
        const scroller = rootRef.current?.closest('main')
        const savedTop = todayLogic.values.homeScrollTop
        if (scroller && typeof savedTop === 'number') {
            scroller.scrollTop = savedTop
            todayLogic.actions.setHomeScrollTop(null)
        }
        return () => {
            if (scroller && reportIdFromPath(router.values.location.pathname)) {
                todayLogic.actions.setHomeScrollTop(scroller.scrollTop)
            }
        }
    }, [])

    useLayoutEffect(() => {
        if (returnFocusReportId === null) {
            return
        }
        rootRef.current
            ?.querySelector<HTMLElement>(`[data-today-report="${CSS.escape(returnFocusReportId)}"]`)
            ?.focus({ preventScroll: true })
        setReturnFocusReportId(null)
    }, [returnFocusReportId, setReturnFocusReportId])

    return (
        <div ref={rootRef} className={cn('TodayHome Today__page', todayNews && 'TodayHome--news')} data-quill>
            <TodaySampleBanner />
            <section className="TodayHome__intro" aria-label="Today">
                <div className="TodayHome__greeting">
                    <Text render={<h1 />} className="m-0 text-[21px] font-[560] tracking-[-0.015em]">
                        {greeting}
                    </Text>
                    {todayNews ? <TodayNewsButton /> : null}
                </div>
                <div className="TodayHome__metaRow">
                    <TodayMetaLine />
                    {!todayNews && !pulsePending && highlights && pulsePinsLoaded ? <TodayPulseEditor /> : null}
                </div>
                {todayNews ? <TodayHomeComposer /> : null}
            </section>
            {todayNews ? <TodayNewsDialog /> : null}
            <div className="TodayHome__body">
                {pulsePending ? (
                    <TodayPulseSkeleton />
                ) : highlights && pulseSlots?.length > 0 ? (
                    todayNews ? (
                        <div className="TodayHome__pulse">
                            <TodayPulse metrics={pulseTiles} slots={pulseSlots} />
                            {pulsePinsLoaded ? (
                                <div className="TodayHome__pulseEdit">
                                    <TodayPulseEditor />
                                </div>
                            ) : null}
                        </div>
                    ) : (
                        <TodayPulse metrics={pulseTiles} slots={pulseSlots} />
                    )
                ) : highlights?.status === 'ready' ? (
                    <Text size="sm" variant="muted" render={<p />} className="m-0">
                        Key numbers show here when you or your team open a few trend insights.
                    </Text>
                ) : null}
                {isNewProject && recentObjects.length === 0 ? <TodayExplore /> : <TodayRecents />}
                <TodayForYou />
            </div>
        </div>
    )
}
