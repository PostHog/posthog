import { connect, kea, key, path, props, selectors } from 'kea'
import type { playerMetaLogicType } from './playerMetaLogicType'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import {
    SessionRecordingLogicProps,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { eventWithTime } from '@rrweb/types'
import { PersonType } from '~/types'
import { ceilMsToClosestSecond, findLastIndex, objectsEqual } from 'lib/utils'
import { sessionRecordingsListPropertiesLogic } from '../playlist/sessionRecordingsListPropertiesLogic'

export const playerMetaLogic = kea<playerMetaLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'playerMetaLogic', key]),
    props({} as SessionRecordingLogicProps),
    key((props: SessionRecordingLogicProps) => `${props.playerKey}-${props.sessionRecordingId}`),
    connect((props: SessionRecordingLogicProps) => ({
        values: [
            sessionRecordingDataLogic(props),
            ['sessionPlayerData', 'sessionEventsData', 'sessionPlayerMetaDataLoading', 'windowIds'],
            sessionRecordingPlayerLogic(props),
            ['scale', 'currentTimestamp', 'currentPlayerTime', 'currentSegment'],
            sessionRecordingsListPropertiesLogic,
            ['recordingPropertiesById'],
        ],
        actions: [sessionRecordingDataLogic(props), ['loadRecordingMetaSuccess']],
    })),
    selectors(() => ({
        sessionPerson: [
            (s) => [s.sessionPlayerData],
            (playerData): PersonType | null => {
                return playerData?.person ?? null
            },
        ],
        resolution: [
            (s) => [s.sessionPlayerData, s.currentTimestamp, s.currentSegment],
            (sessionPlayerData, currentTimestamp, currentSegment): { width: number; height: number } | null => {
                // Find snapshot to pull resolution from
                if (!currentTimestamp) {
                    return null
                }
                const snapshots = sessionPlayerData.snapshotsByWindowId[currentSegment?.windowId ?? ''] ?? []

                const currIndex = findLastIndex(
                    snapshots,
                    (s: eventWithTime) => s.timestamp < currentTimestamp && (s.data as any).width
                )

                if (currIndex === -1) {
                    return null
                }
                const snapshot = snapshots[currIndex]
                return {
                    width: snapshot.data?.['width'],
                    height: snapshot.data?.['height'],
                }
            },
            {
                resultEqualityCheck: (prev, next) => {
                    // Only update if the resolution values have changed (not the object reference)
                    // stops PlayerMeta from re-rendering on every player position
                    return objectsEqual(prev, next)
                },
            },
        ],
        startTime: [
            (s) => [s.sessionPlayerData],
            (sessionPlayerData) => {
                return sessionPlayerData.start ?? null
            },
        ],
        currentWindowIndex: [
            (s) => [s.windowIds, s.currentSegment],
            (windowIds, currentSegment) => {
                return windowIds.findIndex((windowId) => windowId === currentSegment?.windowId ?? -1)
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
        sessionProperties: [
            (s) => [s.sessionPlayerData, s.recordingPropertiesById, (_, props) => props],
            (sessionPlayerData, recordingPropertiesById, props) => {
                return recordingPropertiesById[props.sessionRecordingId] ?? sessionPlayerData.person?.properties
            },
        ],
    })),
])
