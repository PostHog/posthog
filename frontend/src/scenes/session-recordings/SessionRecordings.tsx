import { PageHeader } from 'lib/components/PageHeader'
import { teamLogic } from 'scenes/teamLogic'
import { useValues } from 'kea'
import { urls } from 'scenes/urls'
import { SceneExport } from 'scenes/sceneTypes'
import { SessionRecordingsPlaylist } from './playlist/SessionRecordingsPlaylist'
import { AlertMessage } from 'lib/components/AlertMessage'
import { LemonButton } from '@posthog/lemon-ui'
import { Tabs } from 'antd'
import { SessionRecordingsTabs } from '~/types'
import { SavedSessionRecordingPlaylists } from './saved-playlists/SavedSessionRecordingPlaylists'
import { Tooltip } from 'lib/components/Tooltip'
import { humanFriendlyTabName, sessionRecordingsLogic } from './sessionRecordingsLogic'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { IconSettings } from 'lib/components/icons'
import { router } from 'kea-router'
import { openSessionRecordingSettingsDialog } from './settings/SessionRecordingSettings'

export function SessionsRecordings(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { tab, newPlaylistLoading } = useValues(sessionRecordingsLogic)
    const recordingsDisabled = currentTeam && !currentTeam?.session_recording_opt_in

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
                            <Tooltip placement="topRight" title={'Create a new playlist'}>
                                <LemonButton
                                    type="primary"
                                    // onClick={() => {
                                    //     openPlayerNewPlaylistDialog({
                                    //         sessionRecordingId: 'global',
                                    //         playerKey: 'recents',
                                    //     })
                                    // }}
                                    loading={newPlaylistLoading}
                                    data-attr="save-recordings-playlist-button"
                                >
                                    New playlist
                                </LemonButton>
                            </Tooltip>
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
            ) : (
                <SavedSessionRecordingPlaylists tab={SessionRecordingsTabs.Playlists} />
            )}
        </div>
    )
}

export const scene: SceneExport = {
    component: SessionsRecordings,
    logic: sessionRecordingsLogic,
}
