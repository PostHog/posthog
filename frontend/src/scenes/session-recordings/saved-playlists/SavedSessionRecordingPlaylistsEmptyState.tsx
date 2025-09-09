import { useValues } from 'kea'

import { IconPlus } from '@posthog/icons'

import { AccessControlledLemonButton } from 'lib/components/AccessControlledLemonButton'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { getAppContext } from 'lib/utils/getAppContext'

import { AccessControlLevel, AccessControlResourceType, ReplayTabs } from '~/types'

import { createPlaylist } from '../playlist/playlistUtils'
import { savedSessionRecordingPlaylistsLogic } from './savedSessionRecordingPlaylistsLogic'

export function SavedSessionRecordingPlaylistsEmptyState(): JSX.Element {
    const playlistsLogic = savedSessionRecordingPlaylistsLogic({ tab: ReplayTabs.Home })
    const { loadPlaylistsFailed } = useValues(playlistsLogic)
    return loadPlaylistsFailed ? (
        <LemonBanner type="error">Error while trying to load playlist.</LemonBanner>
    ) : (
        <div className="flex items-center justify-center">
            <div className="max-w-248 mt-12 flex flex-col items-center">
                <h2 className="text-xl">There are no collections that match these filters</h2>
                <p className="text-secondary">Once you create a collection, it will show up here.</p>
                <AccessControlledLemonButton
                    type="primary"
                    data-attr="add-session-playlist-button-empty-state"
                    icon={<IconPlus />}
                    onClick={() => void createPlaylist({ type: 'collection' }, true)}
                    minAccessLevel={AccessControlLevel.Editor}
                    resourceType={AccessControlResourceType.SessionRecording}
                    userAccessLevel={
                        getAppContext()?.resource_access_control?.[AccessControlResourceType.SessionRecording]
                    }
                >
                    New collection
                </AccessControlledLemonButton>
            </div>
        </div>
    )
}
