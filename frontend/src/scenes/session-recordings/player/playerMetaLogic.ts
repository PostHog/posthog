import { kea } from 'kea'
import type { playerMetaLogicType } from './playerMetaLogicType'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { eventWithTime } from 'rrweb/typings/types'
import { PersonType, SessionRecordingPlayerProps } from '~/types'
import { ceilMsToClosestSecond, findLastIndex } from 'lib/utils'
import { getEpochTimeFromPlayerPosition } from './playerUtils'
import { sessionRecordingsListLogic } from '../playlist/sessionRecordingsListLogic'

export const playerMetaLogic = kea<playerMetaLogicType>({
    path: (key) => ['scenes', 'session-recordings', 'player', 'playerMetaLogic', key],
    props: {} as SessionRecordingPlayerProps,
    key: (props: SessionRecordingPlayerProps) => `${props.playerKey}-${props.sessionRecordingId}`,
    connect: ({ sessionRecordingId, playerKey }: SessionRecordingPlayerProps) => ({
        values: [
            sessionRecordingDataLogic({ sessionRecordingId }),
            ['sessionPlayerData', 'sessionEventsData'],
            sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }),
            ['currentPlayerPosition', 'scale', 'isSmallPlayer', 'currentPlayerTime'],
            sessionRecordingsListLogic,
            ['sessionRecordings'],
        ],
        actions: [sessionRecordingDataLogic({ sessionRecordingId }), ['loadRecordingMetaSuccess']],
    }),
    reducers: {
        loading: [
            true,
            {
                loadRecordingMetaSuccess: () => false,
            },
        ],
    },
    selectors: ({ props }) => ({
        sessionPerson: [
            (selectors) => [selectors.sessionPlayerData, selectors.sessionRecordings],
            (playerData, sessionRecordings): PersonType | null => {
                if (playerData?.person) {
                    return playerData?.person
                }
                // If the metadata hasn't loaded, then check if the recording is in the recording list
                return (
                    sessionRecordings.find((sessionRecording) => sessionRecording.id === props.sessionRecordingId)
                        ?.person ?? null
                )
            },
        ],
        resolution: [
            (selectors) => [selectors.sessionPlayerData, selectors.currentPlayerPosition],
            (sessionPlayerData, currentPlayerPosition) => {
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
                    (s: eventWithTime) => s.timestamp < currentEpochTime && 'width' in s.data
                )
                if (currIndex === -1) {
                    return null
                }
                const snapshot = snapshots[currIndex]
                return {
                    width: snapshot.data['width'],
                    height: snapshot.data['height'],
                }
            },
        ],
        recordingStartTime: [
            (selectors) => [selectors.sessionPlayerData, selectors.sessionRecordings],
            (sessionPlayerData, sessionRecordings) => {
                const startTimeFromMeta = sessionPlayerData?.metadata?.segments[0]?.startTimeEpochMs
                if (startTimeFromMeta) {
                    return startTimeFromMeta
                }
                // If the metadata hasn't loaded, then check if the recording is in the recording list
                return (
                    sessionRecordings.find((sessionRecording) => sessionRecording.id === props.sessionRecordingId)
                        ?.start_time ?? null
                )
            },
        ],
        windowIds: [
            (selectors) => [selectors.sessionPlayerData],
            (sessionPlayerData) => {
                return Object.keys(sessionPlayerData?.metadata?.startAndEndTimesByWindowId) ?? []
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
                    if (event.event === '$pageview' && (event.playerTime ?? 0) < playerTimeClosestSecond) {
                        return event
                    }
                }
            },
        ],
    }),
})
