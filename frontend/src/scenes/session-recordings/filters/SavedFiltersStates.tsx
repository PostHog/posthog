import { useValues } from 'kea'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { ReplayTabs } from '~/types'

import { savedSessionRecordingPlaylistsLogic } from '../saved-playlists/savedSessionRecordingPlaylistsLogic'

export function SavedFiltersEmptyState(): JSX.Element {
    const playlistsLogic = savedSessionRecordingPlaylistsLogic({ tab: ReplayTabs.Home })
    const { loadPlaylistsFailed } = useValues(playlistsLogic)
    return loadPlaylistsFailed ? (
        <LemonBanner type="error">Error while trying to load saved filters.</LemonBanner>
    ) : (
        <div className="flex items-center justify-center">
            <div className="max-w-248 mt-12 flex flex-col items-center">
                <h2 className="text-xl">You don't have any saved filters yet.</h2>
                <p className="text-secondary">
                    To create a saved filter, you need to have at least one filter applied.
                </p>
            </div>
        </div>
    )
}

export function SavedFiltersLoadingState(): JSX.Element {
    const playlistsLogic = savedSessionRecordingPlaylistsLogic({ tab: ReplayTabs.Home })
    const { loadPlaylistsFailed } = useValues(playlistsLogic)
    return loadPlaylistsFailed ? (
        <LemonBanner type="error">Error while trying to load saved filters.</LemonBanner>
    ) : (
        <div className="flex items-center justify-center">
            <div className="max-w-248 mt-12 flex flex-col items-center">
                <h2 className="text-xl">Loading saved filters...</h2>
                <p className="text-secondary">This may take a few seconds.</p>
            </div>
        </div>
    )
}
