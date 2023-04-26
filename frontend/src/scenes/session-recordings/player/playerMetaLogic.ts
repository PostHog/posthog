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
import { getEpochTimeFromPlayerPosition } from './playerUtils'

export const playerMetaLogic = kea<playerMetaLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'playerMetaLogic', key]),
    props({} as SessionRecordingLogicProps),
    key((props: SessionRecordingLogicProps) => `${props.playerKey}-${props.sessionRecordingId}`),
    connect((props: SessionRecordingLogicProps) => ({
        values: [
            sessionRecordingDataLogic(props),
            ['sessionPlayerData', 'sessionEventsData', 'sessionPlayerMetaDataLoading', 'windowIds'],
            sessionRecordingPlayerLogic(props),
            ['currentPlayerPosition', 'scale', 'currentPlayerTime'],
        ],
        actions: [sessionRecordingDataLogic(props), ['loadRecordingMetaSuccess']],
    })),
    selectors(() => ({
        sessionPerson: [
            (selectors) => [selectors.sessionPlayerData],
            (playerData): PersonType | null => {
                return playerData?.person ?? null
            },
        ],
        resolution: [
            (selectors) => [selectors.sessionPlayerData, selectors.currentPlayerPosition],
            (sessionPlayerData, currentPlayerPosition): { width: number; height: number } | null => {
                // Find snapshot to pull resolution from
                if (!currentPlayerPosition) {
                    return null
                }
                const snapshots = sessionPlayerData.snapshotsByWindowId[currentPlayerPosition.windowId] ?? []

                const currentEpochTime =
                    getEpochTimeFromPlayerPosition(
                        currentPlayerPosition,
                        sessionPlayerData.metadata.startAndEndTimesByWindowId
                    ) ?? 0

                const currIndex = findLastIndex(
                    snapshots,
                    (s: eventWithTime) => s.timestamp < currentEpochTime && (s.data as any).width
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
        recordingStartTime: [
            (selectors) => [selectors.sessionPlayerData],
            (sessionPlayerData) => {
                const startTimeFromMeta = sessionPlayerData?.metadata?.segments[0]?.startTimeEpochMs
                return startTimeFromMeta ?? null
            },
        ],
        currentWindowIndex: [
            (selectors) => [selectors.windowIds, selectors.currentPlayerPosition],
            (windowIds, currentPlayerPosition) => {
                return windowIds.findIndex((windowId) => windowId === currentPlayerPosition?.windowId ?? -1)
            },
        ],
        lastPageviewEvent: [
            (selectors) => [selectors.sessionEventsData, selectors.currentPlayerTime],
            (sessionEventsData, currentPlayerTime) => {
                const events = sessionEventsData?.events || []
                const playerTimeClosestSecond = ceilMsToClosestSecond(currentPlayerTime ?? 0)

                // Go through the events in reverse to find thelatest pageview
                for (let i = events.length - 1; i >= 0; i--) {
                    const event = events[i]
                    if (
                        (event.event === '$screen' || event.event === '$pageview') &&
                        (event.playerTime ?? 0) < playerTimeClosestSecond
                    ) {
                        return event
                    }
                }
            },
        ],
    })),
])
