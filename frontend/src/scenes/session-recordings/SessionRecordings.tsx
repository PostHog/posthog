import { PageHeader } from 'lib/components/PageHeader'
import { teamLogic } from 'scenes/teamLogic'
import { useActions, useValues } from 'kea'
import { urls } from 'scenes/urls'
import { SceneExport } from 'scenes/sceneTypes'
import { sessionRecordingsListLogic } from 'scenes/session-recordings/playlist/sessionRecordingsListLogic'
import { SessionRecordingsPlaylist } from './playlist/SessionRecordingsPlaylist'
import { AlertMessage } from 'lib/components/AlertMessage'
import { LemonButton, Link } from '@posthog/lemon-ui'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { Tabs } from 'antd'
import { SessionRecordingsTabs } from '~/types'
import { SavedSessionRecordingPlaylists } from './saved-playlists/SavedSessionRecordingPlaylists'
import { Tooltip } from 'lib/components/Tooltip'
import { humanFriendlyTabName, sessionRecordingsLogic } from './sessionRecordingsLogic'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { IconPlus } from 'lib/components/icons'
import { router } from 'kea-router'

export function SessionsRecordings(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { tab, newPlaylistLoading } = useValues(sessionRecordingsLogic)
    const { saveNewPlaylist } = useActions(sessionRecordingsLogic)
    const showRecordingPlaylists = !!featureFlags[FEATURE_FLAGS.RECORDING_PLAYLISTS]
    const { filters } = useValues(sessionRecordingsListLogic({ key: 'recents', updateSearchParams: true }))

    const recentRecordings = (
        <>
            <SessionRecordingsPlaylist logicKey="recents" updateSearchParams />
        </>
    )

    return (
        <div>
            <PageHeader
                title={<div>Session Recordings</div>}
                buttons={
                    showRecordingPlaylists ? (
                        <>
                            <Tooltip
                                placement="left"
                                title={
                                    tab === SessionRecordingsTabs.Recent
                                        ? 'Save the currently filters as a dynamic playlist'
                                        : 'Create a new playlist'
                                }
                            >
                                <LemonButton
                                    type="primary"
                                    onClick={() =>
                                        saveNewPlaylist({
                                            filters: tab === SessionRecordingsTabs.Recent ? filters : undefined,
                                        })
                                    }
                                    disabled={newPlaylistLoading}
                                    data-attr="save-recordings-playlist-button"
                                    icon={<IconPlus />}
                                >
                                    {tab === SessionRecordingsTabs.Recent ? 'Save as playlist' : 'Create new playlist'}
                                </LemonButton>
                            </Tooltip>
                        </>
                    ) : undefined
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
            {currentTeam && !currentTeam?.session_recording_opt_in ? (
                <div className="mb-4">
                    <AlertMessage type="info">
                        Session recordings are currently disabled for this project. To use this feature, please go to
                        your <Link to={`${urls.projectSettings()}#recordings`}>project settings</Link> and enable it.
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
