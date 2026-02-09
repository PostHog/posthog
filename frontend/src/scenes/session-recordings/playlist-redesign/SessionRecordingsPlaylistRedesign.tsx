import { SessionRecordingPlaylistLogicProps } from '../playlist/sessionRecordingsPlaylistLogic'
import { InlineFilterBar } from './InlineFilterBar'
import { ReplayCategories } from './ReplayCategories'

export function SessionRecordingsPlaylistRedesign(props: SessionRecordingPlaylistLogicProps): JSX.Element {
    return (
        <div className="w-full h-full flex flex-col">
            <ReplayCategories {...props} />
            <InlineFilterBar {...props} />

            {/* Placeholder for development - Player, Activity Panel, and Playlist sections */}
            <div className="flex flex-col items-center justify-center min-h-96 p-8 text-center bg-surface-secondary border-2 border-dashed border-border-primary rounded m-8">
                <h2 className="text-lg font-semibold mb-4">Session Replay Redesign</h2>
                <p className="mb-2 max-w-xl">
                    Replay category tiles and inline filter bar are now functional above. Player and playlist sections
                    coming in later phases.
                </p>
            </div>
        </div>
    )
}
