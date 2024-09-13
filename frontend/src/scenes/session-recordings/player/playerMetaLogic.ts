import { connect, kea, key, listeners, path, props, selectors } from 'kea'
import { ceilMsToClosestSecond } from 'lib/utils'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerLogicProps,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { PersonType } from '~/types'

import { sessionRecordingsListPropertiesLogic } from '../playlist/sessionRecordingsListPropertiesLogic'
import type { playerMetaLogicType } from './playerMetaLogicType'

export const playerMetaLogic = kea<playerMetaLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'playerMetaLogic', key]),
    props({} as SessionRecordingPlayerLogicProps),
    key((props: SessionRecordingPlayerLogicProps) => `${props.playerKey}-${props.sessionRecordingId}`),
    connect((props: SessionRecordingPlayerLogicProps) => ({
        values: [
            sessionRecordingDataLogic(props),
            [
                'urls',
                'sessionPlayerData',
                'sessionEventsData',
                'sessionPlayerMetaData',
                'sessionPlayerMetaDataLoading',
                'windowIds',
                'trackedWindow',
            ],
            sessionRecordingPlayerLogic(props),
            ['currentTimestamp', 'currentPlayerTime', 'currentSegment', 'windowTitles'],
            sessionRecordingsListPropertiesLogic,
            ['recordingPropertiesById', 'recordingPropertiesLoading'],
        ],
        actions: [
            sessionRecordingDataLogic(props),
            ['loadRecordingMetaSuccess', 'setTrackedWindow'],
            sessionRecordingsListPropertiesLogic,
            ['maybeLoadPropertiesForSessions'],
        ],
    })),
    selectors(() => ({
        sessionPerson: [
            (s) => [s.sessionPlayerData],
            (playerData): PersonType | null => {
                return playerData?.person ?? null
            },
        ],
        startTime: [
            (s) => [s.sessionPlayerData],
            (sessionPlayerData) => {
                return sessionPlayerData.start ?? null
            },
        ],
        lastUrls: [
            (s) => [s.urls, s.currentTimestamp],
            (urls, currentTimestamp): Record<string, string> => {
                if (!urls.length || !currentTimestamp) {
                    return {}
                }

                const windowUrls: Record<string, string> = {}

                // Go through the urls in reverse to find the URL closest but before the current timestamp
                for (let i = urls.length - 1; i >= 0; i--) {
                    const url = urls[i]
                    if (!(url.windowId in windowUrls) && url.timestamp < currentTimestamp) {
                        windowUrls[url.windowId] = url.url
                    }
                }

                return windowUrls
            },
        ],

        latestScreenTitle: [
            (s) => [s.sessionEventsData, s.currentPlayerTime],
            (sessionEventsData, currentPlayerTime): string | null => {
                if (!sessionEventsData?.length) {
                    return null
                }

                const playerTimeClosestSecond = ceilMsToClosestSecond(currentPlayerTime ?? 0)

                const screenEvents = sessionEventsData.filter(
                    (e) => e.event === '$screen' && e.properties['$screen_name']
                )

                // Go through the $screen events in reverse to find the event closest but before the current player time
                for (let i = screenEvents.length - 1; i >= 0; i--) {
                    const event = screenEvents[i]
                    if ((event.playerTime ?? 0) < playerTimeClosestSecond) {
                        return event.properties['$screen_name'] ?? null
                    }
                }

                return null
            },
        ],

        sessionProperties: [
            (s) => [s.sessionPlayerData, s.recordingPropertiesById, (_, props) => props],
            (sessionPlayerData, recordingPropertiesById, props) => {
                return recordingPropertiesById[props.sessionRecordingId] ?? sessionPlayerData.person?.properties
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        loadRecordingMetaSuccess: () => {
            if (values.sessionPlayerMetaData && !values.recordingPropertiesLoading) {
                actions.maybeLoadPropertiesForSessions([values.sessionPlayerMetaData])
            }
        },
    })),
])
