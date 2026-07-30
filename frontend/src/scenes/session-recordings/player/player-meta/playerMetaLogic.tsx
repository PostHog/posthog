import { aiSummaryMock } from './ai-summary.mock'

import { MakeLogicType, actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'
import React from 'react'

import { IconClock, IconCursorClick, IconHourglass, IconKeyboard, IconWarning } from '@posthog/icons'

import { PropertyFilterIcon } from 'lib/components/PropertyFilters/components/PropertyFilterIcon'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Dayjs } from 'lib/dayjs'
import { COUNTRY_CODE_TO_LONG_NAME } from 'lib/utils/country'
import { ceilMsToClosestSecond, humanFriendlyDuration } from 'lib/utils/durations'
import { isEmptyObject } from 'lib/utils/guards'
import { percentage } from 'lib/utils/numbers'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { OverviewItem } from 'scenes/session-recordings/components/OverviewGrid'
import { Timestamp } from 'scenes/session-recordings/player/controller/PlayerControllerTime'
import { sessionRecordingDataCoordinatorLogic } from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'
import {
    SessionRecordingPlayerLogicProps,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { getCoreFilterDefinition, getFirstFilterTypeFor } from '~/taxonomy/helpers'
import { PersonType, PropertyFilterType, SessionRecordingType } from '~/types'

import type {
    RecordingEventType,
    RecordingSegment,
    SessionPlayerData,
    SessionRecordingPropertiesType,
} from '../../../../types'
import { sessionRecordingsListPropertiesLogic } from '../../playlist/sessionRecordingsListPropertiesLogic'
import { SeekbarSegmentRange } from '../controller/SeekbarSegments'
import type { MiniFilterKey } from '../inspector/miniFiltersLogic'
import { playerInspectorLogic } from '../inspector/playerInspectorLogic'
import type { InspectorListItemEvent } from '../inspector/playerInspectorLogic'
import type { InspectorListItem } from '../inspector/playerInspectorLogic'
import { sessionRecordingPinnedPropertiesLogic } from './sessionRecordingPinnedPropertiesLogic'
import { HARDCODED_DISPLAY_LABELS } from './sessionRecordingPinnedPropertiesLogic'
import { sessionSummaryProgressLogic } from './sessionSummaryProgressLogic'
import { SessionSummaryContent, SummarizationProgress } from './types'

const recordingPropertyKeys = ['click_count', 'keypress_count', 'console_error_count'] as const

// The summary backend filters these out before summarizing, so mirror them here: the
// "Summarize" button should be disabled when every event would be filtered away (otherwise
// the user triggers a summary that fails with "This recording has no events to summarize").
// Keep in sync with SESSION_SUMMARY_EVENT_BLOCKLIST and SESSION_EVENTS_REPLAY_CUTOFF_MS in
// ee/hogai/session_summaries/constants.py.
const SUMMARY_EVENT_MINI_FILTER_KEYS = [
    'events-posthog',
    'events-custom',
    'events-pageview',
    'events-autocapture',
    'events-exceptions',
]
const SUMMARY_EVENT_BLOCKLIST = ['$feature_flag_called']
const SUMMARY_EVENTS_REPLAY_CUTOFF_MS = 5000

/**
 * Whether any event would survive the backend summary filters — i.e. is not blocklisted and
 * does not fall within the replay cutoff of the recording start/end. Mirrors the backend so
 * the Summarize button is only enabled when a summary could actually be produced.
 */
export function hasSummarizableEvents(
    eventItems: InspectorListItemEvent[],
    start: Dayjs | null,
    end: Dayjs | null
): boolean {
    return eventItems.some((item) => {
        if (SUMMARY_EVENT_BLOCKLIST.includes(item.data.event)) {
            return false
        }
        if (start && end) {
            const msSinceStart = item.timestamp.diff(start)
            const msTillEnd = end.diff(item.timestamp)
            if (msSinceStart <= SUMMARY_EVENTS_REPLAY_CUTOFF_MS || msTillEnd <= SUMMARY_EVENTS_REPLAY_CUTOFF_MS) {
                return false
            }
        }
        return true
    })
}

function getAllPersonProperties(sessionPlayerMetaData: SessionRecordingType | null): Record<string, any> {
    return sessionPlayerMetaData?.person?.properties ?? {}
}

function canRenderDirectly(value: any): boolean {
    return typeof value === 'string' || typeof value === 'number' || React.isValidElement(value)
}

export function countryTitleFrom(
    recordingProperties: Record<string, any> | undefined,
    personProperties?: Record<string, any> | undefined
): string {
    const props = recordingProperties || personProperties
    if (!props) {
        return ''
    }

    // these prop names are safe between recording and person properties
    // the "initial" person properties share the same name as the event properties
    const country = COUNTRY_CODE_TO_LONG_NAME[props['$geoip_country_code'] as keyof typeof COUNTRY_CODE_TO_LONG_NAME]
    const subdivision = props['$geoip_subdivision_1_name']
    const city = props['$geoip_city_name']

    return [city, subdivision, country].filter(Boolean).join(', ')
}

/**
 * Get human-readable property label and type information
 * @param property - The property key (e.g., '$browser', 'email')
 * @param recordingProperties - Recording properties to determine if it's an event property
 * @returns Object with label, originalKey, and type information
 */
export function getPropertyDisplayInfo(
    property: string,
    recordingProperties?: Record<string, any>
): {
    label: string
    originalKey: string
    type: TaxonomicFilterGroupType
    propertyFilterType?: PropertyFilterType
} {
    const propertyType =
        recordingProperties && property in recordingProperties
            ? // anything the query returned that doesn't match a core definition must be an event property
              getFirstFilterTypeFor(property) || TaxonomicFilterGroupType.EventProperties
            : TaxonomicFilterGroupType.PersonProperties

    const propertyFilterType: PropertyFilterType | undefined =
        propertyType === TaxonomicFilterGroupType.EventProperties
            ? PropertyFilterType.Event
            : propertyType === TaxonomicFilterGroupType.SessionProperties
              ? PropertyFilterType.Session
              : PropertyFilterType.Person

    const label = getCoreFilterDefinition(property, propertyType)?.label ?? property

    return {
        label,
        originalKey: property,
        type: propertyType,
        propertyFilterType,
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface playerMetaLogicValues {
    allItemsByMiniFilterKey: Record<MiniFilterKey, InspectorListItem[]> // playerInspectorLogic
    sessionEventsData: RecordingEventType[] | null // sessionRecordingDataCoordinatorLogic
    sessionPlayerData: SessionPlayerData // sessionRecordingDataCoordinatorLogic
    sessionPlayerMetaData: SessionRecordingType | null // sessionRecordingDataCoordinatorLogic
    trackedWindow: number | null // sessionRecordingDataCoordinatorLogic
    urls: {
        timestamp: number
        url: string
    }[] // sessionRecordingDataCoordinatorLogic
    windowIds: number[] // sessionRecordingDataCoordinatorLogic
    pinnedProperties: string[] // sessionRecordingPinnedPropertiesLogic
    currentPlayerTime: number // sessionRecordingPlayerLogic
    currentSegment: RecordingSegment | null // sessionRecordingPlayerLogic
    currentTimestamp: number | undefined // sessionRecordingPlayerLogic
    currentURL: string | undefined // sessionRecordingPlayerLogic
    resolution: {
        height: number
        width: number
    } | null // sessionRecordingPlayerLogic
    scale: number // sessionRecordingPlayerLogic
    recordingPropertiesById: Record<string, SessionRecordingPropertiesType[]> // sessionRecordingsListPropertiesLogic
    recordingPropertiesLoading: boolean // sessionRecordingsListPropertiesLogic
    errorBySessionId: Record<string, string | null> // sessionSummaryProgressLogic
    feedbackBySessionId: Record<string, boolean> // sessionSummaryProgressLogic
    loadingBySessionId: Record<string, boolean> // sessionSummaryProgressLogic
    progressBySessionId: Record<string, SummarizationProgress | null> // sessionSummaryProgressLogic
    retryStateBySessionId: Record<
        string,
        {
            hasRetried: boolean
            maxStep: number
        }
    > // sessionSummaryProgressLogic
    summaryBySessionId: Record<string, SessionSummaryContent | null> // sessionSummaryProgressLogic
    summaryIdBySessionId: Record<string, string | null> // sessionSummaryProgressLogic
    allOverviewItems: OverviewItem[]
    currentWindowIndex: number
    displayOverviewItems: OverviewItem[]
    endTime: Dayjs | null
    isPropertyPopoverOpen: boolean
    lastPageviewEvent: RecordingEventType | null | undefined
    loading: boolean
    resolutionDisplay: string
    scaleDisplay: string
    sessionPerson: PersonType | null
    sessionSummary: SessionSummaryContent | null
    sessionSummaryError: string | null
    sessionSummaryHasRetried: boolean
    sessionSummaryId: string | null
    sessionSummaryLoading: boolean
    sessionSummarySegmentRanges: SeekbarSegmentRange[] | null
    showFeedbackSurvey: boolean
    snapshotAt: any
    startTime: Dayjs | null
    summarizationProgress: SummarizationProgress | null
    summaryDisabledReason: string | undefined
    summaryHasHadFeedback: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface playerMetaLogicActions {
    loadRecordingMetaSuccess: (
        sessionPlayerMetaData: SessionRecordingType | null,
        payload?:
            | {
                  value: true
              }
            | undefined
    ) => {
        payload?: {
            value: true
        }
        sessionPlayerMetaData: SessionRecordingType | null
    } // sessionRecordingDataCoordinatorLogic
    setTrackedWindow: (windowId: number | null) => {
        windowId: number | null
    } // sessionRecordingDataCoordinatorLogic
    setPinnedProperties: (properties: string[]) => {
        properties: string[]
    } // sessionRecordingPinnedPropertiesLogic
    togglePropertyPin: (propertyKey: string) => {
        propertyKey: string
    } // sessionRecordingPinnedPropertiesLogic
    loadPropertiesForSessionsSuccess: (
        recordingProperties: SessionRecordingPropertiesType[],
        payload?:
            | {
                  sessions: SessionRecordingType[]
              }
            | undefined
    ) => {
        payload?: {
            sessions: SessionRecordingType[]
        }
        recordingProperties: SessionRecordingPropertiesType[]
    } // sessionRecordingsListPropertiesLogic
    maybeLoadPropertiesForSessions: (sessions: SessionRecordingType[]) => {
        sessions: SessionRecordingType[]
    } // sessionRecordingsListPropertiesLogic
    markFeedbackGiven: (sessionId: string) => {
        sessionId: string
    } // sessionSummaryProgressLogic
    setSummary: (
        sessionId: string,
        summary: SessionSummaryContent | null,
        summaryId?: string | null | undefined
    ) => {
        sessionId: string
        summary: SessionSummaryContent | null
        summaryId: string | null
    } // sessionSummaryProgressLogic
    startSummarization: (sessionId: string) => {
        sessionId: string
    } // sessionSummaryProgressLogic
    sessionSummaryFeedback: (feedback: 'bad' | 'good') => {
        feedback: 'bad' | 'good'
    }
    setIsPropertyPopoverOpen: (isOpen: boolean) => {
        isOpen: boolean
    }
    setShowFeedbackSurvey: (show: boolean) => {
        show: boolean
    }
    summarizeSession: () => {}
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface playerMetaLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        sessionSummary: (
            summaryBySessionId: Record<string, SessionSummaryContent | null>
        ) => SessionSummaryContent | null
        sessionSummaryId: (summaryIdBySessionId: Record<string, string | null>) => string | null
        sessionSummaryLoading: (loadingBySessionId: Record<string, boolean>) => boolean
        summarizationProgress: (
            progressBySessionId: Record<string, SummarizationProgress | null>
        ) => SummarizationProgress | null
        sessionSummaryError: (errorBySessionId: Record<string, string | null>) => string | null
        sessionSummaryHasRetried: (
            retryStateBySessionId: Record<
                string,
                {
                    hasRetried: boolean
                    maxStep: number
                }
            >
        ) => boolean
        summaryHasHadFeedback: (feedbackBySessionId: Record<string, boolean>) => boolean
        summaryDisabledReason: (
            allItemsByMiniFilterKey: Record<string, InspectorListItem[]>,
            sessionPlayerData: SessionPlayerData
        ) => string | undefined
        loading: (
            sessionPlayerMetaData: SessionRecordingType | null,
            recordingPropertiesById: Record<string, SessionRecordingPropertiesType[]>
        ) => boolean
        sessionPerson: (sessionPlayerData: SessionPlayerData) => PersonType | null
        resolutionDisplay: (
            resolution: {
                height: number
                width: number
            } | null
        ) => string
        scaleDisplay: (scale: number) => string
        startTime: (sessionPlayerData: SessionPlayerData) => Dayjs | null
        endTime: (sessionPlayerData: SessionPlayerData) => Dayjs | null
        snapshotAt: (startTime: Dayjs | null) => any
        currentWindowIndex: (currentSegment: null | import('@common/replay-shared/src').RecordingSegment) => number
        lastPageviewEvent: (
            sessionEventsData: RecordingEventType[] | null,
            currentPlayerTime: number
        ) => RecordingEventType | null | undefined
        allOverviewItems: (
            sessionPlayerMetaData: SessionRecordingType | null,
            startTime: Dayjs | null,
            recordingPropertiesById: Record<string, SessionRecordingPropertiesType[]>,
            pinnedProperties: string[]
        ) => OverviewItem[]
        displayOverviewItems: (allOverviewItems: OverviewItem[], pinnedProperties: string[]) => OverviewItem[]
        sessionSummarySegmentRanges: (sessionSummary: SessionSummaryContent | null) => SeekbarSegmentRange[] | null
    }
}

export type playerMetaLogicType = MakeLogicType<
    playerMetaLogicValues,
    playerMetaLogicActions,
    SessionRecordingPlayerLogicProps,
    playerMetaLogicMeta
>

export const playerMetaLogic = kea<playerMetaLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'playerMetaLogic', key]),
    props({} as SessionRecordingPlayerLogicProps),
    key((props: SessionRecordingPlayerLogicProps) => `${props.playerKey}-${props.sessionRecordingId}`),
    connect((props: SessionRecordingPlayerLogicProps) => ({
        values: [
            sessionRecordingDataCoordinatorLogic(props),
            ['urls', 'sessionPlayerData', 'sessionEventsData', 'sessionPlayerMetaData', 'windowIds', 'trackedWindow'],
            sessionRecordingPlayerLogic(props),
            ['scale', 'currentTimestamp', 'currentPlayerTime', 'currentSegment', 'currentURL', 'resolution'],
            sessionRecordingsListPropertiesLogic,
            ['recordingPropertiesById', 'recordingPropertiesLoading'],
            sessionRecordingPinnedPropertiesLogic,
            ['pinnedProperties'],
            sessionSummaryProgressLogic,
            [
                'loadingBySessionId',
                'progressBySessionId',
                'summaryBySessionId',
                'summaryIdBySessionId',
                'feedbackBySessionId',
                'errorBySessionId',
                'retryStateBySessionId',
            ],
            playerInspectorLogic(props),
            ['allItemsByMiniFilterKey'],
        ],
        actions: [
            sessionRecordingDataCoordinatorLogic(props),
            ['loadRecordingMetaSuccess', 'setTrackedWindow'],
            sessionRecordingsListPropertiesLogic,
            ['maybeLoadPropertiesForSessions', 'loadPropertiesForSessionsSuccess'],
            sessionRecordingPinnedPropertiesLogic,
            ['setPinnedProperties', 'togglePropertyPin'],
            sessionSummaryProgressLogic,
            ['startSummarization', 'setSummary', 'markFeedbackGiven'],
        ],
    })),
    actions({
        sessionSummaryFeedback: (feedback: 'good' | 'bad') => ({ feedback }),
        summarizeSession: () => ({}),
        setIsPropertyPopoverOpen: (isOpen: boolean) => ({ isOpen }),
        setShowFeedbackSurvey: (show: boolean) => ({ show }),
    }),
    reducers(() => ({
        showFeedbackSurvey: [
            false,
            {
                setShowFeedbackSurvey: (_, { show }) => show,
            },
        ],
        isPropertyPopoverOpen: [
            false,
            {
                setIsPropertyPopoverOpen: (_, { isOpen }) => isOpen,
            },
        ],
    })),
    selectors(({ props }) => ({
        sessionSummary: [
            (s) => [s.summaryBySessionId],
            (summaryBySessionId: Record<string, SessionSummaryContent | null>): SessionSummaryContent | null =>
                summaryBySessionId[props.sessionRecordingId] ?? null,
        ],
        sessionSummaryId: [
            (s) => [s.summaryIdBySessionId],
            (summaryIdBySessionId: Record<string, string | null>): string | null =>
                summaryIdBySessionId[props.sessionRecordingId] ?? null,
        ],
        sessionSummaryLoading: [
            (s) => [s.loadingBySessionId],
            (loadingBySessionId: Record<string, boolean>): boolean => !!loadingBySessionId[props.sessionRecordingId],
        ],
        summarizationProgress: [
            (s) => [s.progressBySessionId],
            (progressBySessionId: Record<string, SummarizationProgress | null>): SummarizationProgress | null =>
                progressBySessionId[props.sessionRecordingId] ?? null,
        ],
        sessionSummaryError: [
            (s) => [s.errorBySessionId],
            (errorBySessionId: Record<string, string | null>): string | null =>
                errorBySessionId[props.sessionRecordingId] ?? null,
        ],
        sessionSummaryHasRetried: [
            (s) => [s.retryStateBySessionId],
            (
                retryStateBySessionId: Record<
                    string,
                    {
                        hasRetried: boolean
                        maxStep: number
                    }
                >
            ): boolean => !!retryStateBySessionId[props.sessionRecordingId]?.hasRetried,
        ],
        summaryHasHadFeedback: [
            (s) => [s.feedbackBySessionId],
            (feedbackBySessionId: Record<string, boolean>): boolean => !!feedbackBySessionId[props.sessionRecordingId],
        ],
        summaryDisabledReason: [
            (s) => [s.allItemsByMiniFilterKey, s.sessionPlayerData],
            (
                allItemsByMiniFilterKey: Record<
                    import('../inspector/miniFiltersLogic').MiniFilterKey,
                    import('../inspector/playerInspectorLogic').InspectorListItem[]
                >,
                sessionPlayerData: import('~/types').SessionPlayerData
            ): string | undefined => {
                const eventItems = SUMMARY_EVENT_MINI_FILTER_KEYS.flatMap(
                    (key) => allItemsByMiniFilterKey[key] ?? []
                ).filter((item): item is InspectorListItemEvent => item.type === 'events')
                if (eventItems.length === 0) {
                    return 'Session events are not available yet. Try again in a few minutes.'
                }
                return hasSummarizableEvents(eventItems, sessionPlayerData.start ?? null, sessionPlayerData.end ?? null)
                    ? undefined
                    : 'This recording has no events to summarize.'
            },
        ],
        loading: [
            (s) => [s.sessionPlayerMetaData, s.recordingPropertiesById],
            (
                sessionPlayerMetaData: SessionRecordingType | null,
                recordingPropertiesById: Record<string, import('~/types').SessionRecordingPropertiesType[]>
            ) => {
                const hasSessionPlayerMetadata = !!sessionPlayerMetaData && !isEmptyObject(sessionPlayerMetaData)
                const hasRecordingProperties = !!recordingPropertiesById && !isEmptyObject(recordingPropertiesById)
                return !hasSessionPlayerMetadata || !hasRecordingProperties
            },
        ],
        sessionPerson: [
            (s) => [s.sessionPlayerData],
            (playerData: import('~/types').SessionPlayerData): PersonType | null => {
                return playerData?.person ?? null
            },
        ],
        resolutionDisplay: [
            (s) => [s.resolution],
            (
                resolution: {
                    height: number
                    width: number
                } | null
            ) => {
                return `${resolution?.width || '--'} x ${resolution?.height || '--'}`
            },
        ],
        scaleDisplay: [
            (s) => [s.scale],
            (scale: number) => {
                return `${percentage(scale, 1, true)}`
            },
        ],
        startTime: [
            (s) => [s.sessionPlayerData],
            (sessionPlayerData: import('~/types').SessionPlayerData) => {
                return sessionPlayerData.start ?? null
            },
        ],
        endTime: [
            (s) => [s.sessionPlayerData],
            (sessionPlayerData: import('~/types').SessionPlayerData) => {
                return sessionPlayerData.end ?? null
            },
        ],
        snapshotAt: [
            (s) => [s.startTime],
            (startTime: Dayjs | null) => {
                return startTime
                    ? ((startTime as any).toISOString?.() ??
                          (typeof startTime === 'string' ? startTime : String(startTime)))
                    : undefined
            },
        ],
        currentWindowIndex: [
            (s) => [s.currentSegment],
            (currentSegment: null | import('~/types').RecordingSegment) => {
                // windowId is already 1-indexed from the registry
                return currentSegment?.windowId ?? 1
            },
        ],
        lastPageviewEvent: [
            (s) => [s.sessionEventsData, s.currentPlayerTime],
            (sessionEventsData: import('~/types').RecordingEventType[] | null, currentPlayerTime: number) => {
                const playerTimeClosestSecond = ceilMsToClosestSecond(currentPlayerTime ?? 0)

                if (!sessionEventsData?.length) {
                    return null
                }

                // Go through the events in reverse to find the latest pageview
                for (let i = sessionEventsData.length - 1; i >= 0; i--) {
                    const event = sessionEventsData[i]
                    if (
                        (event.event === '$screen' || event.event === '$pageview') &&
                        (event.playerTime ?? 0) < playerTimeClosestSecond
                    ) {
                        return event
                    }
                }
            },
        ],
        allOverviewItems: [
            (s) => [s.sessionPlayerMetaData, s.startTime, s.recordingPropertiesById, s.pinnedProperties],
            (
                sessionPlayerMetaData: SessionRecordingType | null,
                startTime: string | null,
                recordingPropertiesById: Record<string, Record<string, any>>,
                pinnedProperties: string[]
            ) => {
                const items: OverviewItem[] = []

                if (startTime) {
                    items.push({
                        label: 'Start',
                        icon: <IconClock />,
                        value: <Timestamp size="small" noPadding hideIcon fixedTimestamp={startTime} />,
                        type: 'text',
                    })
                }
                if (sessionPlayerMetaData?.recording_duration) {
                    items.push({
                        label: 'Duration',
                        icon: <IconClock />,
                        value: humanFriendlyDuration(sessionPlayerMetaData.recording_duration),
                        type: 'text',
                    })
                }
                if (sessionPlayerMetaData?.retention_period_days && sessionPlayerMetaData?.recording_ttl) {
                    items.push({
                        icon: <IconHourglass />,
                        label: 'TTL',
                        value: `${sessionPlayerMetaData.recording_ttl}d / ${sessionPlayerMetaData.retention_period_days}d`,
                        type: 'text',
                        keyTooltip: 'The number of days left before this recording expires',
                    })
                }

                recordingPropertyKeys.forEach((property) => {
                    if (sessionPlayerMetaData?.[property] !== undefined) {
                        items.push({
                            icon:
                                property === 'click_count' ? (
                                    <IconCursorClick />
                                ) : property === 'keypress_count' ? (
                                    <IconKeyboard />
                                ) : property === 'console_error_count' ? (
                                    <IconWarning />
                                ) : undefined,
                            label:
                                getCoreFilterDefinition(property, TaxonomicFilterGroupType.Replay)?.label ?? property,
                            value: `${sessionPlayerMetaData[property]}`,
                            type: 'text',
                        })
                    }
                })

                const recordingProperties = sessionPlayerMetaData?.id
                    ? recordingPropertiesById[sessionPlayerMetaData?.id] || {}
                    : {}
                const personProperties = getAllPersonProperties(sessionPlayerMetaData)

                // Combine both recording and person properties
                const allProperties = { ...recordingProperties, ...personProperties }
                if (allProperties['$os_name'] && allProperties['$os']) {
                    // we don't need both, prefer $os_name in case mobile sends better value in that field
                    delete allProperties['$os']
                }

                const allPropertyKeys = new Set(Object.keys(allProperties))

                // There may be pinned properties that don't exist as keys on this specific user,
                // we still want to show them, albeit with a value of '-'.
                // However, we don't want to add duplicates for hardcoded processed properties like "Start", "Duration", "TTL"...
                pinnedProperties.forEach((property: string) => {
                    if (!allPropertyKeys.has(property) && !HARDCODED_DISPLAY_LABELS.includes(property as any)) {
                        allPropertyKeys.add(property)
                    }
                })

                Array.from(allPropertyKeys).forEach((property) => {
                    if (property === '$geoip_subdivision_1_name' || property === '$geoip_city_name') {
                        // they're just shown in the title for Country
                        return
                    }

                    // Skip recording property keys that we've already processed
                    if (recordingPropertyKeys.includes(property as any)) {
                        return
                    }

                    const propertyInfo = getPropertyDisplayInfo(property, recordingProperties)
                    const value = allProperties[property]

                    const safeValue =
                        value == null
                            ? '-'
                            : typeof value === 'string'
                              ? value
                              : typeof value === 'number'
                                ? value.toString()
                                : JSON.stringify(value, null, 2)

                    items.push({
                        icon: <PropertyFilterIcon type={propertyInfo.propertyFilterType} />,
                        label: propertyInfo.label,
                        value: safeValue,
                        keyTooltip:
                            propertyInfo.label !== propertyInfo.originalKey
                                ? `Sent as: ${propertyInfo.originalKey}`
                                : propertyInfo.propertyFilterType
                                  ? `${capitalizeFirstLetter(propertyInfo.propertyFilterType)} property`
                                  : undefined,
                        valueTooltip:
                            property === '$geoip_country_code' && safeValue in COUNTRY_CODE_TO_LONG_NAME
                                ? countryTitleFrom(recordingProperties, personProperties)
                                : // we don't want to pass arbitrary objects to the overview grid's tooltip here, so we stringify them
                                  canRenderDirectly(value)
                                  ? value
                                  : JSON.stringify(value),
                        type: 'property',
                        property,
                    })
                })

                return items
            },
        ],
        displayOverviewItems: [
            (s) => [s.allOverviewItems, s.pinnedProperties],
            (allOverviewItems: OverviewItem[], pinnedProperties: string[]) => {
                // Filter to show only pinned properties and sort by pinned order
                const pinnedItems = allOverviewItems.filter((item) => {
                    const key = item.type === 'property' ? item.property : item.label
                    return pinnedProperties.includes(String(key))
                })

                // Sort by the order in pinnedProperties array
                // without this pins jump around as they load in
                return pinnedItems.sort((a, b) => {
                    const aKey = a.type === 'property' ? a.property : a.label
                    const bKey = b.type === 'property' ? b.property : b.label
                    const aIndex = pinnedProperties.indexOf(String(aKey))
                    const bIndex = pinnedProperties.indexOf(String(bKey))
                    return aIndex - bIndex
                })
            },
        ],
        sessionSummarySegmentRanges: [
            (s) => [s.sessionSummary],
            (sessionSummary: SessionSummaryContent | null) => {
                if (!sessionSummary?.segments || !sessionSummary?.key_actions) {
                    return null
                }
                const ranges: SeekbarSegmentRange[] = []
                for (const segment of sessionSummary.segments) {
                    if (segment.index == null || !segment.name) {
                        continue
                    }
                    const segmentKeyActions = sessionSummary.key_actions.filter(
                        (ka) => ka.segment_index === segment.index
                    )
                    const allEvents = segmentKeyActions.flatMap((ka) => ka.events ?? [])
                    const validEvents = allEvents.filter(
                        (e) => e.milliseconds_since_start != null && e.milliseconds_since_start >= 0
                    )
                    if (validEvents.length === 0) {
                        continue
                    }
                    const startMs = Math.min(...validEvents.map((e) => e.milliseconds_since_start!))
                    const endMs = Math.max(...validEvents.map((e) => e.milliseconds_since_start!))
                    const outcome = sessionSummary.segment_outcomes?.find((o) => o.segment_index === segment.index)
                    ranges.push({
                        index: segment.index,
                        name: segment.name,
                        startMs,
                        endMs: endMs > startMs ? endMs : startMs + 1000,
                        success: outcome?.success ?? null,
                    })
                }
                return ranges.length > 0 ? ranges : null
            },
        ],
    })),
    listeners(({ actions, values, props }) => {
        // Skip if the list-wide fetch is in flight; calling again cancels it via breakpoint.
        const maybeLoadRecordingProperties = (): void => {
            if (values.sessionPlayerMetaData && !values.recordingPropertiesLoading) {
                actions.maybeLoadPropertiesForSessions([values.sessionPlayerMetaData])
            }
        }
        return {
            // a newly pinned session property may not be in the cached recording properties yet
            setPinnedProperties: maybeLoadRecordingProperties,
            loadRecordingMetaSuccess: () => {
                maybeLoadRecordingProperties()
                if (
                    values.sessionPlayerMetaData?.has_summary &&
                    !values.sessionSummary &&
                    !values.sessionSummaryLoading
                ) {
                    actions.summarizeSession()
                }
            },
            sessionSummaryFeedback: ({ feedback }) => {
                posthog.capture('session summary feedback', {
                    feedback,
                    session_summary: values.sessionSummary,
                    summary_id: values.sessionSummaryId,
                    summarized_session_id: props.sessionRecordingId,
                })
                actions.markFeedbackGiven(props.sessionRecordingId)
            },
            summarizeSession: () => {
                // TODO: Remove after testing
                const local = false
                if (local) {
                    actions.setSummary(props.sessionRecordingId, aiSummaryMock)
                    return
                }
                const id = props.sessionRecordingId || props.sessionRecordingData?.sessionRecordingId
                if (!id) {
                    return
                }
                // delegates the SSE stream + per-session state to the singleton so progress survives navigating away and back mid-stream
                actions.startSummarization(id)
            },
        }
    }),
])
