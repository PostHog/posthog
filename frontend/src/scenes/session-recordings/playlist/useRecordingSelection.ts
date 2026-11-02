import { useActions, useValues } from 'kea'

import { SessionRecordingType } from '~/types'

import { MAX_SELECTED_RECORDINGS, sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

export function useRecordingSelection(recording: SessionRecordingType): {
    checked: boolean
    disabledReason: string | undefined
    toggle: () => void
} {
    const { selectedRecordingsIds } = useValues(sessionRecordingsPlaylistLogic)
    const { setSelectedRecordingsIds } = useActions(sessionRecordingsPlaylistLogic)
    const checked = selectedRecordingsIds.some((s) => s === recording.id)
    return {
        checked,
        disabledReason:
            !checked && selectedRecordingsIds.length >= MAX_SELECTED_RECORDINGS
                ? `Cannot select more than ${MAX_SELECTED_RECORDINGS} recordings at once`
                : undefined,
        toggle: () => {
            if (checked) {
                setSelectedRecordingsIds(selectedRecordingsIds.filter((r) => r !== recording.id))
            } else {
                setSelectedRecordingsIds([...selectedRecordingsIds, recording.id])
            }
        },
    }
}
