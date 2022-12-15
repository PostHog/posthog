import { PageHeader } from 'lib/components/PageHeader'
import { teamLogic } from 'scenes/teamLogic'
import { useActions, useValues } from 'kea'
import { urls } from 'scenes/urls'
import { SceneExport } from 'scenes/sceneTypes'
import { SessionRecordingsPlaylist } from './playlist/SessionRecordingsPlaylist'
import { AlertMessage } from 'lib/components/AlertMessage'
import { LemonButton } from '@posthog/lemon-ui'
import { Tabs } from 'antd'
import { SessionRecordingsTabs } from '~/types'
import { SavedSessionRecordingPlaylists } from './saved-playlists/SavedSessionRecordingPlaylists'
import { humanFriendlyTabName, sessionRecordingsLogic } from './sessionRecordingsLogic'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { IconSettings } from 'lib/components/icons'
import { router } from 'kea-router'
import { openSessionRecordingSettingsDialog } from './settings/SessionRecordingSettings'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { SessionRecordingFilePlayback } from './file-playback/SessionRecodingFilePlayback'
import { createPlaylist } from './playlist/playlistUtils'
import { useAsyncHandler } from 'lib/hooks/useAsyncHandler'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

export function SessionsRecordings(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { tab } = useValues(sessionRecordingsLogic)
    const recordingsDisabled = currentTeam && !currentTeam?.session_recording_opt_in
    const { featureFlags } = useValues(featureFlagLogic)
    const { reportRecordingPlaylistCreated } = useActions(eventUsageLogic)

    const visibleTabs = [SessionRecordingsTabs.Recent, SessionRecordingsTabs.Playlists]

    if (!featureFlags[FEATURE_FLAGS.RECORDINGS_EXPORT]) {
        visibleTabs.push(SessionRecordingsTabs.FilePlayback)
    }

    const newPlaylistHandler = useAsyncHandler(async () => {
        await createPlaylist({}, true)
        reportRecordingPlaylistCreated('new')
    })

    return (
        <div>
            <PageHeader
                title={<div>Session Recordings</div>}
                buttons={
                    <>
                        {tab === SessionRecordingsTabs.Recent && !recordingsDisabled && (
                            <LemonButton
                                type="secondary"
                                icon={<IconSettings />}
                                onClick={() => openSessionRecordingSettingsDialog()}
                            >
                                Configure
                            </LemonButton>
                        )}

                        {tab === SessionRecordingsTabs.Playlists && (
                            <LemonButton
                                type="primary"
                                onClick={newPlaylistHandler.onEvent}
                                data-attr="save-recordings-playlist-button"
                                loading={newPlaylistHandler.loading}
                            >
                                New playlist
                            </LemonButton>
                        )}
                    </>
                }
            />
            <Tabs
                activeKey={tab}
                animated={false}
                style={{ borderColor: '#D9D9D9' }}
                onChange={(t) => router.actions.push(urls.sessionRecordings(t as SessionRecordingsTabs))}
            >
                {Object.values(SessionRecordingsTabs).map((value) => (
                    <Tabs.TabPane tab={humanFriendlyTabName(value)} key={value} />
                ))}
            </Tabs>
            {recordingsDisabled ? (
                <div className="mb-4">
                    <AlertMessage
                        type="info"
                        action={{
                            type: 'secondary',
                            icon: <IconSettings />,
                            onClick: () => openSessionRecordingSettingsDialog(),
                            children: 'Configure',
                        }}
                    >
                        Session recordings are currently disabled for this project.
                    </AlertMessage>
                </div>
            ) : null}
            {!tab ? (
                <Spinner />
            ) : tab === SessionRecordingsTabs.Recent ? (
                <SessionRecordingsPlaylist updateSearchParams />
            ) : tab === SessionRecordingsTabs.Playlists ? (
                <SavedSessionRecordingPlaylists tab={SessionRecordingsTabs.Playlists} />
            ) : tab === SessionRecordingsTabs.FilePlayback ? (
                <SessionRecordingFilePlayback />
            ) : null}
        </div>
    )
}

export const scene: SceneExport = {
    component: SessionsRecordings,
    logic: sessionRecordingsLogic,
}
