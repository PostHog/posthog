import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useRef, useState } from 'react'

import { HedgehogDirector } from '@posthog/brand/hoggies'

import api from 'lib/api'
import { CardTopHeadingRow } from 'lib/components/Cards/CardTopHeadingRow'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { toParams } from 'lib/utils/url'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import 'scenes/session-recordings/playlist/SessionRecordingPreview.scss'
import {
    SessionRecordingPreview,
    SessionRecordingPreviewSkeleton,
} from 'scenes/session-recordings/playlist/SessionRecordingPreview'
import { sessionRecordingEventUsageLogic } from 'scenes/session-recordings/sessionRecordingEventUsageLogic'

import type { RecordingsQuery } from '~/queries/schema/schema-general'
import type { SessionRecordingType } from '~/types'

import {
    WidgetCardBodyMessage,
    WidgetCardContent,
    WidgetContentFooter,
    WidgetListCount,
    WIDGET_LIST_COUNT_RECORDINGS,
} from '../../components/WidgetCard'
import type { DashboardWidgetTopHeadingProps } from '../../components/WidgetCard/WidgetCardHeader'
import type { DashboardWidgetComponentProps } from '../registry'
import { parseSessionReplayWidgetConfig } from './sessionReplayWidgetConfigValidation'
import { sessionReplayWidgetSavedFiltersLogic } from './sessionReplayWidgetSavedFiltersLogic'

type SessionReplayWidgetResult = {
    results?: SessionRecordingType[]
    hasMore?: boolean
    limit?: number
    totalCount?: number
    totalCountCapped?: boolean
    /**
     * Filters the backend used to build this list (saved filter resolved server-side), so the player
     * can highlight the matching events. Absent when nothing can match. The client adds session_ids.
     */
    matchingEventsQuery?: RecordingsQuery
}

function SessionReplayWidgetRecordingRow({
    recording,
    order,
    matchingEventsQuery,
}: {
    recording: SessionRecordingType
    order: RecordingsQuery['order']
    /** Base query (filters minus session id) used to fetch the events to highlight, or null when nothing can match. */
    matchingEventsQuery: RecordingsQuery | null
}): JSX.Element {
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)
    const { reportRecordingOpenedFromRecentRecordingList } = useActions(sessionRecordingEventUsageLogic)
    const [isOpening, setIsOpening] = useState(false)
    // Ref guard, not the state value: state updates aren't visible to a second click that fires
    // before the next render, so two rapid clicks would otherwise both pass the guard.
    const isOpeningRef = useRef(false)

    const openRecording = async (): Promise<void> => {
        if (isOpeningRef.current) {
            return
        }
        reportRecordingOpenedFromRecentRecordingList()

        // No event/property filters means there's nothing to highlight — open straight away.
        if (!matchingEventsQuery) {
            openSessionPlayer({ id: recording.id })
            return
        }

        isOpeningRef.current = true
        setIsOpening(true)
        try {
            const query: RecordingsQuery = { ...matchingEventsQuery, session_ids: [recording.id] }
            const response = await api.recordings.getMatchingEvents(toParams(query))
            openSessionPlayer({
                id: recording.id,
                matching_events: [{ session_id: recording.id, events: response.results }],
            })
        } catch (error) {
            // Highlighting matching events is best-effort; fall back to opening without it, but
            // surface the failure so a systematically broken query doesn't degrade silently.
            posthog.captureException(error, { feature: 'session-replay-widget-matching-events' })
            openSessionPlayer({ id: recording.id })
        } finally {
            isOpeningRef.current = false
            setIsOpening(false)
        }
    }

    return (
        <div
            className={clsx('relative border-b', isOpening && 'pointer-events-none opacity-60')}
            onClick={() => void openRecording()}
            aria-busy={isOpening}
        >
            <SessionRecordingPreview recording={recording} order={order} />
            {isOpening && (
                <div className="absolute inset-y-0 right-2 flex items-center">
                    <Spinner />
                </div>
            )}
        </div>
    )
}

export function SessionReplayWidget({ result, loading, config }: DashboardWidgetComponentProps): JSX.Element {
    const payload = result as SessionReplayWidgetResult | null | undefined
    const recordings = payload?.results ?? []
    const parsedConfig = parseSessionReplayWidgetConfig(config)
    const order = parsedConfig.orderBy as RecordingsQuery['order']
    const matchingEventsQuery = payload?.matchingEventsQuery ?? null

    if (loading) {
        return (
            <WidgetCardContent>
                {Array.from({ length: 4 }, (_, index) => (
                    <div key={index} className="border-b">
                        <SessionRecordingPreviewSkeleton />
                    </div>
                ))}
            </WidgetCardContent>
        )
    }

    if (recordings.length === 0) {
        return (
            <WidgetCardContent>
                <WidgetCardBodyMessage>
                    <div
                        className="flex max-w-xs flex-col items-center gap-2 px-2 text-balance"
                        data-attr="session-replay-widget-empty-state"
                    >
                        <HedgehogDirector className="size-20 shrink-0" />
                        <p className="m-0 text-base font-semibold text-primary">No recordings yet</p>
                        <p className="m-0 text-sm text-muted">No session recordings matched your filters.</p>
                    </div>
                </WidgetCardBodyMessage>
            </WidgetCardContent>
        )
    }

    return (
        <>
            <WidgetCardContent>
                <div className="flex flex-col">
                    {recordings.map((recording) => (
                        <SessionReplayWidgetRecordingRow
                            key={recording.id}
                            recording={recording}
                            order={order}
                            matchingEventsQuery={matchingEventsQuery}
                        />
                    ))}
                </div>
            </WidgetCardContent>
            <WidgetContentFooter>
                <WidgetListCount
                    shown={recordings.length}
                    totalCount={payload?.totalCount}
                    totalCountIsLowerBound={payload?.totalCountCapped}
                    noun={WIDGET_LIST_COUNT_RECORDINGS}
                    hasMore={payload?.hasMore}
                    dataAttr="session-replay-widget-count"
                />
            </WidgetContentFooter>
        </>
    )
}

// A collection or saved filter scopes the widget instead of its date range, so the header shows their
// names in place — e.g. "My collection · My filter" when both are set.
export function SessionReplayWidgetTopHeading({
    config,
    widgetTypeLabel,
    showWidgetType,
    dateText,
}: DashboardWidgetTopHeadingProps): JSX.Element {
    const asShortId = (value: unknown): string | null => (typeof value === 'string' && value.length > 0 ? value : null)
    const savedFilterId = asShortId(config.savedFilterId)
    const collectionId = asShortId(config.collectionId)
    const { savedFilterLabelById, collectionLabelById } = useValues(sessionReplayWidgetSavedFiltersLogic)

    const scopeParts: string[] = []
    if (collectionId) {
        scopeParts.push(collectionLabelById[collectionId] ?? 'Collection')
    }
    if (savedFilterId) {
        scopeParts.push(savedFilterLabelById[savedFilterId] ?? 'Saved filter')
    }

    return (
        <CardTopHeadingRow
            typeLabel={widgetTypeLabel}
            showTypeLabel={showWidgetType}
            dateText={scopeParts.length > 0 ? scopeParts.join(' · ') : dateText}
        />
    )
}
