import { BuiltLogic } from 'kea'
import { RefObject } from 'react'
import { SessionRecordingPlayerMode } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { PersonUUID } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import type { sessionRecordingsPlaylistLogicType } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogicType'

import { RecordingUniversalFilters, SessionPlayerData, SessionRecordingId, SessionRecordingType } from '~/types'

interface NoEventsToMatch {
    matchType: 'none'
}

interface EventNamesMatching {
    matchType: 'name'
    eventNames: string[]
}

interface EventUUIDsMatching {
    matchType: 'uuid'
    eventUUIDs: string[]
}

interface BackendEventsMatching {
    matchType: 'backend'
    filters: RecordingUniversalFilters
}

export type MatchingEventsMatchType = NoEventsToMatch | EventNamesMatching | EventUUIDsMatching | BackendEventsMatching

// the logics that use the props below mount each other
// the complexity of the interfaces below
// is to keep track of how they mount each other more clearly

interface SessionRecordingDataKey {
    sessionRecordingId: SessionRecordingId
}

export interface SessionRecordingDataLogicProps extends SessionRecordingDataKey {
    realTimePollingIntervalMilliseconds?: number
}

export interface SessionRecordingPlayerLogicKey {
    playerKey: string
    sessionRecordingId: SessionRecordingId
}

export interface SessionRecordingPlayerLogicProps extends SessionRecordingPlayerLogicKey, SessionRecordingDataKey {
    sessionRecordingData?: SessionPlayerData
    matchingEventsMatchType?: MatchingEventsMatchType
    playlistLogic?: BuiltLogic<sessionRecordingsPlaylistLogicType>
    autoPlay?: boolean
    mode?: SessionRecordingPlayerMode
    playerRef?: RefObject<HTMLDivElement>
    pinned?: boolean
    setPinned?: (pinned: boolean) => void
}

export interface PlayerInspectorLogicProps extends SessionRecordingPlayerLogicKey {
    matchingEventsMatchType?: MatchingEventsMatchType
}

export interface NetworkViewLogicProps extends SessionRecordingDataKey {}

export interface PerformanceEventDataLogicProps extends SessionRecordingDataKey {}

interface SessionRecordingPlaylistLogicKey {
    logicKey?: string
    personUUID?: PersonUUID
    updateSearchParams?: boolean
}

export interface SessionRecordingPlaylistLogicProps extends SessionRecordingPlaylistLogicKey {
    autoPlay?: boolean
    filters?: RecordingUniversalFilters
    onFiltersChange?: (filters: RecordingUniversalFilters) => void
    pinnedRecordings?: (SessionRecordingType | string)[]
    onPinnedChange?: (recording: SessionRecordingType, pinned: boolean) => void
}
