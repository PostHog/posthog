import { aiSummaryMock } from './ai-summary.mock'

import { createParser } from 'eventsource-parser'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'
import React from 'react'

import { IconCursorClick, IconHourglass, IconKeyboard, IconWarning } from '@posthog/icons'

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
import { calculateTTL } from '../utils/ttlUtils'
import type { playerMetaLogicType } from './playerMetaLogicType'
import { SessionSummaryContent } from './types'

const recordingPropertyKeys = ['click_count', 'keypress_count', 'console_error_count'] as const

const ALLOW_LISTED_PERSON_PROPERTIES = [
    '$os_name',
    '$os',
    '$browser_name',
    '$browser',
    '$device_type',
    '$referrer',
    '$geoip_country_code',
    '$geoip_subdivision_1_name',
    '$geoip_city_name',
]

function allowListedPersonProperties(sessionPlayerMetaData: SessionRecordingType | null): Record<string, any> {
    const personProperties = sessionPlayerMetaData?.person?.properties ?? {}
    return Object.fromEntries(
        Object.entries(personProperties).filter(([key]) => {
            return ALLOW_LISTED_PERSON_PROPERTIES.includes(key)
        })
    )
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
        sessionTTLDays: [
            (s) => [s.sessionPlayerMetaData],
            (sessionPlayerMetaData) => {
                if (sessionPlayerMetaData?.retention_period_days && sessionPlayerMetaData?.start_time) {
                    return calculateTTL(sessionPlayerMetaData.start_time, sessionPlayerMetaData.retention_period_days)
                }

                return null
            },
        ],
        overviewItems: [
            (s) => [s.sessionPlayerMetaData, s.startTime, s.recordingPropertiesById, s.sessionTTLDays],
            (sessionPlayerMetaData, startTime, recordingPropertiesById, sessionTTLDays) => {
                const items: OverviewItem[] = []
                if (startTime) {
                    items.push({
                        label: 'Start',
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
                        value: humanFriendlyDuration(sessionPlayerMetaData.recording_duration),
                        type: 'text',
                    })
                }
                if (sessionPlayerMetaData?.retention_period_days) {
                    items.push({
                        label: 'Retention Period',
                        value: `${sessionPlayerMetaData.retention_period_days}d`,
                        type: 'text',
                        keyTooltip: 'The total number of days this recording will be retained',
                    })
                }
                if (sessionTTLDays !== null) {
                    items.push({
                        icon: <IconHourglass />,
                        label: 'TTL',
                        value: `${sessionTTLDays}d`,
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
                const personProperties = allowListedPersonProperties(sessionPlayerMetaData)

                const shouldUsePersonProperties = Object.keys(recordingProperties).length === 0
                const propertiesToUse = shouldUsePersonProperties ? personProperties : recordingProperties
                if (propertiesToUse['$os_name'] && propertiesToUse['$os']) {
                    // we don't need both, prefer $os_name in case mobile sends better value in that field
                    delete propertiesToUse['$os']
                }
                Object.entries(propertiesToUse).forEach(([property, value]) => {
                    if (value == null) {
                        return
                    }
                    if (property === '$geoip_subdivision_1_name' || property === '$geoip_city_name') {
                        // they're just shown in the title for Country
                        return
                    }

                    const propertyType = recordingProperties[property]
                        ? // HogQL query can return multiple types, so we need to check
                          // but if it doesn't match a core definition it must be an event property
                          getFirstFilterTypeFor(property) || TaxonomicFilterGroupType.EventProperties
                        : TaxonomicFilterGroupType.PersonProperties

                    const safeValue =
                        typeof value === 'string'
                            ? value
                            : typeof value === 'number'
                              ? value.toString()
                              : JSON.stringify(value, null, 2)

                    const calculatedPropertyType: PropertyFilterType | undefined = shouldUsePersonProperties
                        ? PropertyFilterType.Person
                        : propertyType === TaxonomicFilterGroupType.EventProperties
                          ? PropertyFilterType.Event
                          : TaxonomicFilterGroupType.SessionProperties
                            ? PropertyFilterType.Session
                            : PropertyFilterType.Person
                    items.push({
                        icon: <PropertyFilterIcon type={calculatedPropertyType} />,
                        label: getCoreFilterDefinition(property, propertyType)?.label ?? property,
                        value: safeValue,
                        keyTooltip: calculatedPropertyType
                            ? `${capitalizeFirstLetter(calculatedPropertyType)} property`
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
