import { PageHeader } from 'lib/components/PageHeader'
import { teamLogic } from 'scenes/teamLogic'
import { useValues } from 'kea'
import { urls } from 'scenes/urls'
import { SceneExport } from 'scenes/sceneTypes'
import { sessionRecordingsListLogic } from 'scenes/session-recordings/playlist/sessionRecordingsListLogic'
import { SessionRecordingsPlaylist } from './playlist/SessionRecordingsPlaylist'
import { SessionRecordingsTopBar } from './filters/SessionRecordingsTopBar'
import { AlertMessage } from 'lib/components/AlertMessage'
import { LemonButton, Link } from '@posthog/lemon-ui'
import { openSessionRecordingSettingsDialog } from './settings/SessionRecordingSettings'
import { IconSettings } from 'lib/components/icons'

export function SessionsRecordings(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <div className="space-y-4">
            <PageHeader
                title={<div>Recordings</div>}
                buttons={
                    <>
                        <LemonButton
                            type="secondary"
                            sideIcon={<IconSettings />}
                            onClick={() => openSessionRecordingSettingsDialog()}
                        >
                            Configure
                        </LemonButton>
                    </>
                }
            />
            {currentTeam && !currentTeam?.session_recording_opt_in ? (
                <div className="mb-4">
                    <AlertMessage type="info">
                        Session recordings are currently disabled for this project. To use this feature, please go to
                        your <Link to={`${urls.projectSettings()}#recordings`}>project settings</Link> and enable it.
                    </AlertMessage>
                </div>
            ) : null}
            <SessionRecordingsTopBar />
            <SessionRecordingsPlaylist key="global" />
        </div>
    )
}

export const scene: SceneExport = {
    component: SessionsRecordings,
    logic: sessionRecordingsListLogic,
}
