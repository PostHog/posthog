import { useValues } from 'kea'

import { IconPlus } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { createPlaylist } from '../playlist/playlistUtils'
import { sessionRecordingCollectionsLogic } from './sessionRecordingCollectionsLogic'

export function SessionRecordingCollectionsEmptyState(): JSX.Element {
    const { loadPlaylistsFailed } = useValues(sessionRecordingCollectionsLogic)
    return loadPlaylistsFailed ? (
        <LemonBanner type="error">Error while trying to load playlist.</LemonBanner>
    ) : (
        <div className="flex items-center justify-center">
            <div className="max-w-248 mt-12 flex flex-col items-center">
                <h2 className="text-xl">There are no collections that match these filters</h2>
                <p className="text-secondary">Once you create a collection, it will show up here.</p>
                <AccessControlAction
                    resourceType={AccessControlResourceType.SessionRecording}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <LemonButton
                        type="primary"
                        data-attr="add-session-playlist-button-empty-state"
                        icon={<IconPlus />}
                        onClick={() => void createPlaylist({ type: 'collection' }, true)}
                    >
                        New collection
                    </LemonButton>
                </AccessControlAction>
            </div>
        </div>
    )
}
