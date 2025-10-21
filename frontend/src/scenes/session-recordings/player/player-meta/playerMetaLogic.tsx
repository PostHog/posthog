import { aiSummaryMock } from './ai-summary.mock'

import { createParser } from 'eventsource-parser'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'
import React from 'react'

import { IconClock, IconCursorClick, IconHourglass, IconKeyboard, IconWarning } from '@posthog/icons'

import api from 'lib/api'
import { PropertyFilterIcon } from 'lib/components/PropertyFilters/components/PropertyFilterIcon'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
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
import type { playerMetaLogicType } from './playerMetaLogicType'
import { SessionSummaryContent } from './types'

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
        ],
        actions: [
            sessionRecordingDataCoordinatorLogic(props),
            ['loadRecordingMetaSuccess', 'setTrackedWindow'],
            sessionRecordingsListPropertiesLogic,
            ['maybeLoadPropertiesForSessions', 'loadPropertiesForSessionsSuccess'],
        ],
    })),
    actions({
        sessionSummaryFeedback: (feedback: 'good' | 'bad') => ({ feedback }),
        setSessionSummaryContent: (content: SessionSummaryContent) => ({ content }),
        summarizeSession: () => ({}),
        setSessionSummaryLoading: (isLoading: boolean) => ({ isLoading }),
        setPinnedProperties: (properties: string[]) => ({ properties }),
        togglePropertyPin: (propertyKey: string) => ({ propertyKey }),
        setIsPropertyPopoverOpen: (isOpen: boolean) => ({ isOpen }),
    }),
    reducers(() => ({
        summaryHasHadFeedback: [
            false,
            {
                sessionSummaryFeedback: () => true,
            },
        ],
        sessionSummary: [
            null as SessionSummaryContent | null,
            {
                setSessionSummaryContent: (_, { content }) => content,
            },
        ],
        sessionSummaryLoading: [
            false,
            {
                summarizeSession: () => true,
                setSessionSummaryContent: () => false,
                setSessionSummaryLoading: (_, { isLoading }) => isLoading,
            },
        ],
        pinnedProperties: [
            [
                'Start',
                'Clicks',
                'Duration',
                'TTL',
                'console_error_count',
                'click_count',
                'key_press_count',
                '$referrer',
                '$geoip_country_code',
                '$geoip_city_name',
            ] as string[],
            { persist: true },
            {
                setPinnedProperties: (_, { properties }) => properties,
            },
        ],
        isPropertyPopoverOpen: [
            false,
            {
                setIsPropertyPopoverOpen: (_, { isOpen }) => isOpen,
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        togglePropertyPin: ({ propertyKey }) => {
            const currentPinned = values.pinnedProperties
            if (currentPinned.includes(propertyKey)) {
                actions.setPinnedProperties(currentPinned.filter((k) => k !== propertyKey))
            } else {
                actions.setPinnedProperties([...currentPinned, propertyKey])
            }
        },
    })),
    selectors(() => ({
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
        currentWindowIndex: [
            (s) => [s.windowIds, s.currentSegment],
            (windowIds, currentSegment) => {
                const index = windowIds.findIndex((windowId) =>
                    currentSegment?.windowId ? windowId === currentSegment?.windowId : -1
                )
                return index === -1 ? 1 : index + 1
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
            (s) => [s.sessionPlayerMetaData, s.startTime, s.recordingPropertiesById],
            (sessionPlayerMetaData, startTime, recordingPropertiesById) => {
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
                        icon: <IconHourglass />,
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
                    if (sessionPlayerMetaData?.[property]) {
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
                Object.entries(allProperties).forEach(([property, value]) => {
                    if (property === '$geoip_subdivision_1_name' || property === '$geoip_city_name') {
                        // they're just shown in the title for Country
                        return
                    }

                    const propertyInfo = getPropertyDisplayInfo(property, recordingProperties)

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
                        keyTooltip: propertyInfo.propertyFilterType
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
                // Filter to show only pinned properties
                return allOverviewItems.filter((item) => {
                    const key = item.type === 'property' ? item.property : item.label
                    return pinnedProperties.includes(String(key))
                })
            },
        ],
    })),
    listeners(({ actions, values, props }) => ({
        loadRecordingMetaSuccess: () => {
            if (values.sessionPlayerMetaData) {
                actions.maybeLoadPropertiesForSessions([values.sessionPlayerMetaData])
            }
        },
        sessionSummaryFeedback: ({ feedback }) => {
            posthog.capture('session summary feedback', {
                feedback,
                session_summary: values.sessionSummary,
                summarized_session_id: props.sessionRecordingId,
            })
        },
        // Using listener instead of loader to be able to stream the summary chunks (as loaders wait for the whole response)
        summarizeSession: async () => {
            // TODO: Remove after testing
            const local = false
            if (local) {
                actions.setSessionSummaryContent(aiSummaryMock)
                return
            }
            // TODO: Stop loading/reset the state when failing to avoid endless "thinking" state
            const id = props.sessionRecordingId || props.sessionRecordingData?.sessionRecordingId
            if (!id) {
                return
            }
            try {
                const response = await api.recordings.summarizeStream(id)
                const reader = response.body?.getReader()
                if (!reader) {
                    throw new Error('No reader available')
                }
                const decoder = new TextDecoder()
                const parser = createParser({
                    onEvent: ({ event, data }) => {
                        try {
                            // Stop loading and show error if encountered an error event
                            if (event === 'session-summary-error') {
                                lemonToast.error(data)
                                actions.setSessionSummaryLoading(false)
                                return
                            }
                            const parsedData = JSON.parse(data)
                            if (parsedData) {
                                actions.setSessionSummaryContent(parsedData)
                            }
                        } catch {
                            // Don't handle errors as we can afford to fail some chunks silently.
                            // However, there should not be any unparseable chunks coming from the server as they are validated before being sent.
                        }
                    },
                })
                // Consume stream until exhausted
                while (true) {
                    const { done, value } = await reader.read()
                    if (done) {
                        break
                    }
                    const decodedValue = decoder.decode(value)
                    parser.feed(decodedValue)
                }
            } catch (err) {
                lemonToast.error('Failed to load session summary. Please, contact us, and try again in a few minutes.')
                throw err
            } finally {
                actions.setSessionSummaryLoading(false)
            }
        },
    })),
])
