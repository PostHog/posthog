import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useLayoutEffect, useRef } from 'react'

import { Text } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { organizationLogic } from 'scenes/organizationLogic'

import { TodayExplore } from './TodayExplore'
import { TodayFirstEventWatcher } from './TodayFirstEventWatcher'
import { TodayForYou } from './TodayForYou'
import { todayHighlightsLogic } from './todayHighlightsLogic'
import { TodayHomeComposer } from './TodayHomeComposer'
import { reportIdFromPath, todayLogic } from './todayLogic'
import { TodayPromoBanner } from './TodayPromoBanner'
import { TodayPulseSection } from './TodayPulseSection'
import { TodayRecents } from './TodayRecents'
import { TodaySampleBanner } from './TodaySampleBanner'

const DATE_FORMAT = new Intl.DateTimeFormat(undefined, { weekday: 'long', day: 'numeric', month: 'long' })

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
    const {
        greeting,
        isNewProject,
        recentObjects,
        recentsHasLoaded,
        frequentObjectsLoading,
        returnFocusReportId,
        useSampleData,
    } = useValues(todayLogic)
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
    } = useValues(todayHighlightsLogic)
    const { pulseViewMounted, pulseViewUpdated, pulseViewUnmounted } = useActions(todayHighlightsLogic)
    const rootRef = useRef<HTMLDivElement>(null)
    const { currentOrganization } = useValues(organizationLogic)
    const postHogAiTasks = useFeatureFlag('PHAI_SANDBOX_MODE')
    const homeComposer = postHogAiTasks && !!currentOrganization?.is_ai_data_processing_approved

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
        <div ref={rootRef} className="TodayHome Today__page" data-quill>
            <TodaySampleBanner />
            <TodayPromoBanner />
            <section className="TodayHome__intro" aria-label="Today">
                <div className="TodayHome__greeting">
                    <Text render={<h1 />} className="m-0 text-[21px] font-[560] tracking-[-0.015em]">
                        {greeting}
                    </Text>
                </div>
                <TodayMetaLine />
                {homeComposer ? <TodayHomeComposer /> : null}
            </section>
            <div className="TodayHome__body">
                {isNewProject ? <TodayFirstEventWatcher /> : <TodayPulseSection />}
                {isNewProject ? <TodayForYou /> : null}
                {recentsHasLoaded && !frequentObjectsLoading && recentObjects.length === 0 ? (
                    <TodayExplore />
                ) : (
                    <TodayRecents />
                )}
                {isNewProject ? null : <TodayForYou />}
            </div>
        </div>
    )
}
