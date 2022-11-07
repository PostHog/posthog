import { PageHeader } from 'lib/components/PageHeader'
import { teamLogic } from 'scenes/teamLogic'
import { useActions, useValues } from 'kea'
import { urls } from 'scenes/urls'
import { SceneExport } from 'scenes/sceneTypes'
import { sessionRecordingsListLogic } from 'scenes/session-recordings/playlist/sessionRecordingsListLogic'
import { SessionRecordingsPlaylist } from './playlist/SessionRecordingsPlaylist'
import { SessionRecordingsTopBar } from './filters/SessionRecordingsTopBar'
import { AlertMessage } from 'lib/components/AlertMessage'
import { Link } from '@posthog/lemon-ui'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { Tabs } from 'antd'
import { SessionRecordingPlaylistsTabs } from '~/types'

export function SessionsRecordings(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { tab } = useValues(sessionRecordingsListLogic)
    const { setTab } = useActions(sessionRecordingsListLogic)
    const showRecordingPlaylists = !!featureFlags[FEATURE_FLAGS.RECORDING_PLAYLISTS]

    const recentRecordings = (
        <>
            <SessionRecordingsTopBar />
            <SessionRecordingsPlaylist key="global" />
        </>
    )

    return (
        <div>
            <PageHeader title={<div>Recordings</div>} />
            {showRecordingPlaylists && (
                <Tabs
                    activeKey={tab}
                    style={{ borderColor: '#D9D9D9' }}
                    onChange={(t) => setTab(t as SessionRecordingPlaylistsTabs)}
                >
                    <Tabs.TabPane tab="Recent recordings" key={SessionRecordingPlaylistsTabs.Recent} />
                    <Tabs.TabPane tab="All Playlists" key={SessionRecordingPlaylistsTabs.All} />
                    <Tabs.TabPane tab="Your Playlists" key={SessionRecordingPlaylistsTabs.Yours} />
                    <Tabs.TabPane tab="Pinned" key={SessionRecordingPlaylistsTabs.Pinned} />
                    <Tabs.TabPane tab="History" key={SessionRecordingPlaylistsTabs.History} />
                </Tabs>
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
                tab === SessionRecordingPlaylistsTabs.Recent ? (
                    recentRecordings
                ) : (
                    <div>WIP</div>
                )
            ) : (
                recentRecordings
            )}
        </div>
    )
}

export const scene: SceneExport = {
    component: SessionsRecordings,
    logic: sessionRecordingsListLogic,
}
