import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { SessionRecordingsPlaylist } from './SessionRecordingsPlaylist'
import { SessionRecordingPlaylistLogicProps, sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'
import { sessionRecordingsPlaylistSceneLogic } from './sessionRecordingsPlaylistSceneLogic'

function AddSelectedFooter({
    playlistProps,
    shortId,
    onClose,
}: {
    playlistProps: SessionRecordingPlaylistLogicProps
    shortId: string
    onClose: () => void
}): JSX.Element {
    const { selectedRecordingsIds } = useValues(sessionRecordingsPlaylistLogic(playlistProps))
    const { handleBulkAddToPlaylist } = useActions(sessionRecordingsPlaylistLogic(playlistProps))
    const count = selectedRecordingsIds.length

    return (
        <div className="flex justify-end gap-2">
            <LemonButton data-attr="collection-add-modal-close" type="secondary" onClick={onClose}>
                Done
            </LemonButton>
            <LemonButton
                type="primary"
                disabledReason={count === 0 ? 'Select recordings in the list first' : undefined}
                onClick={() => handleBulkAddToPlaylist(shortId)}
                data-attr="collection-add-selected-recordings"
            >
                Add {count} {count === 1 ? 'recording' : 'recordings'}
            </LemonButton>
        </div>
    )
}

export function AddRecordingsToCollectionModal(): JSX.Element | null {
    const { playlist, isAddRecordingsModalOpen } = useValues(sessionRecordingsPlaylistSceneLogic)
    const { setAddRecordingsModalOpen, onPinnedChange } = useActions(sessionRecordingsPlaylistSceneLogic)

    if (!playlist) {
        return null
    }

    const playlistProps: SessionRecordingPlaylistLogicProps = {
        logicKey: `add-recordings-${playlist.short_id}`,
        type: 'filters',
        updateSearchParams: false,
        autoPlay: true,
        onlyPinned: false,
        onPinnedChange,
    }
    const close = (): void => setAddRecordingsModalOpen(false)

    return (
        <LemonModal
            isOpen={isAddRecordingsModalOpen}
            onClose={close}
            title={`Add recordings to ${playlist.name || playlist.derived_name || 'this collection'}`}
            description="Filter the list, tick the recordings you want, then add them."
            width="90vw"
            maxWidth="90vw"
            footer={<AddSelectedFooter playlistProps={playlistProps} shortId={playlist.short_id} onClose={close} />}
        >
            <div className="h-[75vh]">
                <SessionRecordingsPlaylist {...playlistProps} />
            </div>
        </LemonModal>
    )
}
