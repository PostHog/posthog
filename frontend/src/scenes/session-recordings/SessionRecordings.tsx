import { PageHeader } from 'lib/components/PageHeader'
import { teamLogic } from 'scenes/teamLogic'
import { useActions, useValues } from 'kea'
import { urls } from 'scenes/urls'
import { SceneExport } from 'scenes/sceneTypes'
import { SessionRecordingsPlaylist } from './playlist/SessionRecordingsPlaylist'
import { AlertMessage } from 'lib/components/AlertMessage'
import { LemonButton } from '@posthog/lemon-ui'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { Tabs } from 'antd'
import { SessionRecordingsTabs } from '~/types'
import { SavedSessionRecordingPlaylists } from './saved-playlists/SavedSessionRecordingPlaylists'
import { Tooltip } from 'lib/components/Tooltip'
import { humanFriendlyTabName, sessionRecordingsLogic } from './sessionRecordingsLogic'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { IconPlus, IconSettings } from 'lib/components/icons'
import { router } from 'kea-router'
import { openSessionRecordingSettingsDialog } from './settings/SessionRecordingSettings'

export function SessionsRecordings(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { tab, newPlaylistLoading } = useValues(sessionRecordingsLogic)
    const { saveNewPlaylist } = useActions(sessionRecordingsLogic)
    const showRecordingPlaylists = !!featureFlags[FEATURE_FLAGS.RECORDING_PLAYLISTS]
    const recentRecordings = <SessionRecordingsPlaylist logicKey="recents" updateSearchParams />

    const recordingsDisabled = currentTeam && !currentTeam?.session_recording_opt_in

    return (
        <div>
            <PageHeader
                title={<div>Session Recordings</div>}
                buttons={
                    <>
                        {!recordingsDisabled && (
                            <LemonButton
                                type="secondary"
                                icon={<IconSettings />}
                                onClick={() => openSessionRecordingSettingsDialog()}
                            >
                                Configure
                            </LemonButton>
                        )}

                        {showRecordingPlaylists ? (
                            <>
                                <Tooltip
                                    placement="topRight"
                                    title={
                                        tab === SessionRecordingsTabs.Recent
                                            ? 'Save the currently filters as a dynamic playlist'
                                            : 'Create a new playlist'
                                    }
                                >
                                    <LemonButton
                                        type="primary"
                                        onClick={() => saveNewPlaylist()}
                                        loading={newPlaylistLoading}
                                        data-attr="save-recordings-playlist-button"
                                        icon={<IconPlus />}
                                    >
                                        {tab === SessionRecordingsTabs.Recent
                                            ? 'Save as playlist'
                                            : 'Create new playlist'}
                                    </LemonButton>
                                </Tooltip>
                            </>
                        ) : undefined}
                    </>
                }
            />
            {showRecordingPlaylists && (
                <>
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
                </>
            )}
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
            {showRecordingPlaylists ? (
                !tab ? (
                    <Spinner />
                ) : tab === SessionRecordingsTabs.Recent ? (
                    recentRecordings
                ) : (
                    <SavedSessionRecordingPlaylists tab={SessionRecordingsTabs.Playlists} />
                )
            ) : (
                recentRecordings
            )}
        </div>
    )
}

export const scene: SceneExport = {
    component: SessionsRecordings,
    logic: sessionRecordingsLogic,
}
