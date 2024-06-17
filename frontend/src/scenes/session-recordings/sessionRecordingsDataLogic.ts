import { actions, kea, path, props } from 'kea'
import type { sessionRecordingsDataLogicType } from './sessionRecordingsDataLogicType'
import { PersonUUID } from './playlist/sessionRecordingsPlaylistLogic'
import { RecordingFilters, RecordingUniversalFilters, ReplayTabs, SessionRecordingType } from '~/types'

export interface SessionRecordingsDataLogicProps {
    logicKey?: string
    personUUID?: PersonUUID
    updateSearchParams?: boolean
    autoPlay?: boolean
    hideSimpleFilters?: boolean
    universalFilters?: RecordingUniversalFilters
    advancedFilters?: RecordingFilters
    simpleFilters?: RecordingFilters
    onFiltersChange?: (filters: RecordingFilters) => void
    pinnedRecordings?: (SessionRecordingType | string)[]
    onPinnedChange?: (recording: SessionRecordingType, pinned: boolean) => void
    currentTab?: ReplayTabs
}

export const sessionRecordingsDataLogic = kea<sessionRecordingsDataLogicType>([
    path((key) => ['scenes', 'session-recordings', 'playlist', 'sessionRecordingsDataLogic', key]),
    props({} as SessionRecordingsDataLogicProps),

    actions({}),
])
