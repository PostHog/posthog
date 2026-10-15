import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useLayoutEffect, useRef } from 'react'

import { IconRefresh } from '@posthog/icons'
import { Button, Skeleton, Spinner, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { todayBriefingLogic } from './todayBriefingLogic'
import { TodayExplore } from './TodayExplore'
import { TodayForYou } from './TodayForYou'
import { todayHighlightsLogic } from './todayHighlightsLogic'
import { reportIdFromPath, todayLogic } from './todayLogic'
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
    const { now, currentTeam } = useValues(todayLogic)
    const date = new Date(now)
    return (
        <p className="TodayHome__meta">
            <time translate="no" dateTime={date.toISOString()}>
                {DATE_FORMAT.format(date)}
            </time>
            <span className="whitespace-pre">{` · ${currentTeam?.name ?? 'Your project'}`}</span>
        </p>
    )
}

export function TodayHomePage(): JSX.Element {
    const { greeting, showPersonalBriefing, isNewProject, recentObjects, returnFocusReportId } = useValues(todayLogic)
    const { setReturnFocusReportId } = useActions(todayLogic)
    const { personalBriefing, briefingWaiting } = useValues(todayBriefingLogic)
    const { refreshBriefing } = useActions(todayBriefingLogic)
    const { highlights, highlightsPending } = useValues(todayHighlightsLogic)
    const rootRef = useRef<HTMLDivElement>(null)

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
        <div ref={rootRef} className="TodayHome Today__page" data-quill>
            <TodaySampleBanner />
            <section className="TodayHome__intro" aria-label="Today">
                <div className="TodayHome__greeting">
                    <Text render={<h1 />} className="m-0 text-[21px] font-[560] tracking-[-0.015em]">
                        {greeting}
                    </Text>
                    {briefingWaiting ? (
                        <span className="TodayHome__badge" data-attr="today-briefing-writing">
                            <Spinner />
                            <span>Writing your briefing…</span>
                        </span>
                    ) : showPersonalBriefing || personalBriefing?.status === 'failed' ? (
                        <Tooltip>
                            <TooltipTrigger
                                render={
                                    <Button
                                        variant="link-muted"
                                        size="icon-sm"
                                        className="TodayHome__refresh"
                                        aria-label="Refresh briefing"
                                        onClick={() => refreshBriefing()}
                                        data-attr="today-briefing-refresh"
                                    />
                                }
                            >
                                <IconRefresh className="size-4" />
                            </TooltipTrigger>
                            <TooltipContent>Refresh briefing</TooltipContent>
                        </Tooltip>
                    ) : null}
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
