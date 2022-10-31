import { PageHeader } from 'lib/components/PageHeader'
import { teamLogic } from 'scenes/teamLogic'
import { useValues } from 'kea'
import { SceneExport } from 'scenes/sceneTypes'
import { sessionRecordingsListLogic } from 'scenes/session-recordings/playlist/sessionRecordingsListLogic'
import { SessionRecordingsPlaylist } from './playlist/SessionRecordingsPlaylist'
import { SessionRecordingsTopBar } from './filters/SessionRecordingsTopBar'
import { AlertMessage } from 'lib/components/AlertMessage'
import { LemonButton } from '@posthog/lemon-ui'
import { openSessionRecordingSettingsDialog } from './settings/SessionRecordingSettings'
import { IconSettings } from 'lib/components/icons'

export function SessionsRecordings(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    const recordingsDisabled = currentTeam && !currentTeam?.session_recording_opt_in

    return (
        <div className="space-y-4">
            <PageHeader
                title={<div>Recordings</div>}
                buttons={
                    !recordingsDisabled ? (
                        <>
                            <LemonButton
                                type="secondary"
                                icon={<IconSettings />}
                                onClick={() => openSessionRecordingSettingsDialog()}
                            >
                                Configure
                            </LemonButton>
                        </>
                    ) : undefined
                }
            />
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
            <SessionRecordingsTopBar />
            <SessionRecordingsPlaylist key="global" />
        </div>
    )
}

export const scene: SceneExport = {
    component: SessionsRecordings,
    logic: sessionRecordingsListLogic,
}
