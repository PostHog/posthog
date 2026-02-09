import { useActions, useValues } from 'kea'

import { SessionRecordingCollections } from '../collections/SessionRecordingCollections'
import { SavedFilters } from '../filters/SavedFilters'
import { playlistFiltersLogic } from '../playlist/playlistFiltersLogic'
import {
    SessionRecordingPlaylistLogicProps,
    sessionRecordingsPlaylistLogic,
} from '../playlist/sessionRecordingsPlaylistLogic'
import SessionRecordingTemplates from '../templates/SessionRecordingTemplates'
import { InlineFilterBar } from './InlineFilterBar'
import { ReplayCategories } from './ReplayCategories'

export function SessionRecordingsPlaylistRedesign(props: SessionRecordingPlaylistLogicProps): JSX.Element {
    const { activeCategory } = useValues(playlistFiltersLogic)
    const logic = sessionRecordingsPlaylistLogic(props)
    const { setFilters } = useActions(logic)

    // Categories that show filters and recordings list
    const showInlineFilters = ['browse', 'mobile', 'high_errors', 'engaged'].includes(activeCategory)

    return (
        <div className="w-full h-full flex flex-col">
            <ReplayCategories {...props} />

            {showInlineFilters && <InlineFilterBar {...props} />}

            {/* Conditional content based on active category */}
            {activeCategory === 'saved_filters' && (
                <div className="p-4">
                    <SavedFilters setFilters={setFilters} />
                </div>
            )}

            {activeCategory === 'collections' && (
                <div className="flex-1 overflow-auto">
                    <SessionRecordingCollections />
                </div>
            )}

            {activeCategory === 'quick_stats' && (
                <div className="flex-1 overflow-auto">
                    <SessionRecordingTemplates hideTemplates={true} />
                </div>
            )}

            {showInlineFilters && (
                /* Placeholder for development - Player, Activity Panel, and Playlist sections */
                <div className="flex flex-col items-center justify-center min-h-96 p-8 text-center bg-surface-secondary border-2 border-dashed border-border-primary rounded m-8">
                    <h2 className="text-lg font-semibold mb-4">Session Replay Redesign</h2>
                    <p className="mb-2 max-w-xl">
                        Replay category tiles and inline filter bar are now functional above. Player and playlist
                        sections coming in later phases.
                    </p>
                </div>
            )}
        </div>
    )
}
