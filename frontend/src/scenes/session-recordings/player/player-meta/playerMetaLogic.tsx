import { aiSummaryMock } from './ai-summary.mock'

import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'
import React from 'react'

import { IconClock, IconCursorClick, IconHourglass, IconKeyboard, IconWarning } from '@posthog/icons'

import { PropertyFilterIcon } from 'lib/components/PropertyFilters/components/PropertyFilterIcon'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import {
    capitalizeFirstLetter,
    ceilMsToClosestSecond,
    humanFriendlyDuration,
    isEmptyObject,
    percentage,
} from 'lib/utils'
import { COUNTRY_CODE_TO_LONG_NAME } from 'lib/utils/geography/country'
import { OverviewItem } from 'scenes/session-recordings/components/OverviewGrid'
import { TimestampFormat } from 'scenes/session-recordings/player/playerSettingsLogic'
import { sessionRecordingDataCoordinatorLogic } from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'
import {
    SessionRecordingPlayerLogicProps,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { getCoreFilterDefinition, getFirstFilterTypeFor } from '~/taxonomy/helpers'
import { PersonType, PropertyFilterType, SessionRecordingType } from '~/types'

import { SimpleTimeLabel } from '../../components/SimpleTimeLabel'
import { sessionRecordingsListPropertiesLogic } from '../../playlist/sessionRecordingsListPropertiesLogic'
import { SeekbarSegmentRange } from '../controller/SeekbarSegments'
import { playerInspectorLogic } from '../inspector/playerInspectorLogic'
import type { playerMetaLogicType } from './playerMetaLogicType'
import { sessionRecordingPinnedPropertiesLogic } from './sessionRecordingPinnedPropertiesLogic'
import { HARDCODED_DISPLAY_LABELS } from './sessionRecordingPinnedPropertiesLogic'
import { sessionSummaryProgressLogic } from './sessionSummaryProgressLogic'
import { SessionSummaryContent, SummarizationProgress } from './types'

const recordingPropertyKeys = ['click_count', 'keypress_count', 'console_error_count'] as const

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
    const propertyType = recordingProperties?.[property]
        ? // HogQL query can return multiple types, so we need to check
          // but if it doesn't match a core definition it must be an event property
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
            ['recordingPropertiesById'],
            sessionRecordingPinnedPropertiesLogic,
            ['pinnedProperties'],
            sessionSummaryProgressLogic,
            ['loadingBySessionId', 'progressBySessionId', 'summaryBySessionId', 'feedbackBySessionId'],
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
            (summaryBySessionId): SessionSummaryContent | null => summaryBySessionId[props.sessionRecordingId] ?? null,
        ],
        sessionSummaryLoading: [
            (s) => [s.loadingBySessionId],
            (loadingBySessionId): boolean => !!loadingBySessionId[props.sessionRecordingId],
        ],
        summarizationProgress: [
            (s) => [s.progressBySessionId],
            (progressBySessionId): SummarizationProgress | null =>
                progressBySessionId[props.sessionRecordingId] ?? null,
        ],
        summaryHasHadFeedback: [
            (s) => [s.feedbackBySessionId],
            (feedbackBySessionId): boolean => !!feedbackBySessionId[props.sessionRecordingId],
        ],
        summaryDisabledReason: [
            (s) => [s.allItemsByMiniFilterKey],
            (allItemsByMiniFilterKey): string | undefined => {
                const hasAutocapture = !!allItemsByMiniFilterKey['events-autocapture']?.length
                if (hasAutocapture) {
                    return undefined
                }
                const hasAnyEvents = [
                    'events-posthog',
                    'events-custom',
                    'events-pageview',
                    'events-autocapture',
                    'events-exceptions',
                ].some((key) => allItemsByMiniFilterKey[key]?.length > 0)
                return hasAnyEvents
                    ? 'This session has no autocapture events. Enable autocapture in your project settings to use AI summaries.'
                    : 'Session events are not available yet. Try again in a few minutes.'
            },
        ],
        loading: [
            (s) => [s.sessionPlayerMetaData, s.recordingPropertiesById],
            (sessionPlayerMetaData, recordingPropertiesById) => {
                const hasSessionPlayerMetadata = !!sessionPlayerMetaData && !isEmptyObject(sessionPlayerMetaData)
                const hasRecordingProperties = !!recordingPropertiesById && !isEmptyObject(recordingPropertiesById)
                return !hasSessionPlayerMetadata || !hasRecordingProperties
            },
        ],
        sessionPerson: [
            (s) => [s.sessionPlayerData],
            (playerData): PersonType | null => {
                return playerData?.person ?? null
            },
        ],
        resolutionDisplay: [
            (s) => [s.resolution],
            (resolution) => {
                return `${resolution?.width || '--'} x ${resolution?.height || '--'}`
            },
        ],
        scaleDisplay: [
            (s) => [s.scale],
            (scale) => {
                return `${percentage(scale, 1, true)}`
            },
        ],
        startTime: [
            (s) => [s.sessionPlayerData],
            (sessionPlayerData) => {
                return sessionPlayerData.start ?? null
            },
        ],
        endTime: [
            (s) => [s.sessionPlayerData],
            (sessionPlayerData) => {
                return sessionPlayerData.end ?? null
            },
        ],
        snapshotAt: [
            (s) => [s.startTime],
            (startTime) => {
                return startTime
                    ? ((startTime as any).toISOString?.() ??
                          (typeof startTime === 'string' ? startTime : String(startTime)))
                    : undefined
            },
        ],
        currentWindowIndex: [
            (s) => [s.currentSegment],
            (currentSegment) => {
                // windowId is already 1-indexed from the registry
                return currentSegment?.windowId ?? 1
            },
        ],
        lastPageviewEvent: [
            (s) => [s.sessionEventsData, s.currentPlayerTime],
            (sessionEventsData, currentPlayerTime) => {
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
                        value: (
                            <SimpleTimeLabel
                                muted={false}
                                size="small"
                                timestampFormat={TimestampFormat.UTC}
                                startTime={startTime}
                            />
                        ),
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
            (allOverviewItems, pinnedProperties) => {
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
    listeners(({ actions, values, props }) => ({
        loadRecordingMetaSuccess: () => {
            if (values.sessionPlayerMetaData) {
                actions.maybeLoadPropertiesForSessions([values.sessionPlayerMetaData])
            }
            if (values.sessionPlayerMetaData?.has_summary && !values.sessionSummary && !values.sessionSummaryLoading) {
                actions.summarizeSession()
            }
        },
        sessionSummaryFeedback: ({ feedback }) => {
            posthog.capture('session summary feedback', {
                feedback,
                session_summary: values.sessionSummary,
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
            // Delegates the SSE stream + per-session state to the singleton so that
            // progress survives navigation away from and back to a recording mid-stream.
            actions.startSummarization(id)
        },
    })),
])
