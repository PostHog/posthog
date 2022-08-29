import { kea } from 'kea'
import type { metaLogicType } from './metaLogicType'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { eventWithTime } from 'rrweb/typings/types'
import { PersonType, RecordingEventType, SessionRecordingPlayerProps } from '~/types'
import { findLastIndex } from 'lib/utils'
import { getEpochTimeFromPlayerPosition } from './playerUtils'
import { eventsListLogic } from 'scenes/session-recordings/player/list/eventsListLogic'
import { sessionRecordingsTableLogic } from '../sessionRecordingsTableLogic'

const getPersonProperties = (person: Partial<PersonType>, keys: string[]): string | null => {
    if (keys.some((k) => !person?.properties?.[k])) {
        return null
    }
    return keys.map((k) => person?.properties?.[k]).join(', ')
}

const getEventProperties = (event: RecordingEventType, keys: string[]): string | null => {
    if (keys.some((k) => !event?.properties?.[k])) {
        return null
    }
    return keys.map((k) => event?.properties?.[k]).join(', ')
}

export const metaLogic = kea<metaLogicType>({
    path: ['scenes', 'session-recordings', 'player', 'metaLogic'],
    props: {} as SessionRecordingPlayerProps,
    key: (props: SessionRecordingPlayerProps) => `${props.playerKey}-${props.sessionRecordingId}`,
    connect: ({ sessionRecordingId, playerKey }: SessionRecordingPlayerProps) => ({
        values: [
            sessionRecordingDataLogic({ sessionRecordingId }),
            ['sessionPlayerData', 'eventsToShow'],
            sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }),
            ['currentPlayerPosition', 'scale'],
            eventsListLogic({ sessionRecordingId, playerKey }),
            ['currentStartIndex'],
            sessionRecordingsTableLogic,
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
    selectors: ({ cache, props }) => ({
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
        description: [
            (selectors) => [selectors.sessionPerson],
            (person) => {
                const location = person
                    ? getPersonProperties(person, ['$geoip_city_name', '$geoip_country_code'])
                    : null
                const device = person ? getPersonProperties(person, ['$browser', '$os']) : null
                return [device, location].filter((s) => s).join(' · ')
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
        currentUrl: [
            (selectors) => [selectors.eventsToShow, selectors.currentStartIndex],
            (events, startIndex) => {
                if (startIndex === -1 || !events?.length) {
                    return ''
                }
                const nextUrl = getEventProperties(events[startIndex], ['$current_url']) ?? ''
                cache.previousUrl = nextUrl || cache.previousUrl
                return cache.previousUrl
            },
        ],
    }),
})
