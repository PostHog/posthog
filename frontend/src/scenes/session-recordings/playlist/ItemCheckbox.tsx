import { useActions, useValues } from 'kea'

import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'

import { SessionRecordingType } from '~/types'

import { MAX_SELECTED_RECORDINGS, sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

export function ItemCheckbox({ recording }: { recording: SessionRecordingType }): JSX.Element {
    const { selectedRecordingsIds } = useValues(sessionRecordingsPlaylistLogic)
    const { setSelectedRecordingsIds } = useActions(sessionRecordingsPlaylistLogic)

    const checked = selectedRecordingsIds.some((s) => s === recording.id)
    return (
        <LemonCheckbox
            checked={checked}
            data-attr="select-recording"
            aria-label="Select recording"
            disabledReason={
                !checked && selectedRecordingsIds.length >= MAX_SELECTED_RECORDINGS
                    ? `Cannot select more than ${MAX_SELECTED_RECORDINGS} recordings at once`
                    : undefined
            }
            onChange={() => {
                if (checked) {
                    setSelectedRecordingsIds(selectedRecordingsIds.filter((r) => r !== recording.id))
                } else {
                    setSelectedRecordingsIds([...selectedRecordingsIds, recording.id])
                }
            }}
            stopPropagation
        />
    )
}
