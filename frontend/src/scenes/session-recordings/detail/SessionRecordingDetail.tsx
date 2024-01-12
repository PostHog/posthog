import './SessionRecordingScene.scss'

import { useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'
import {
    sessionRecordingDetailLogic,
    SessionRecordingDetailLogicProps,
} from 'scenes/session-recordings/detail/sessionRecordingDetailLogic'
import { RecordingNotFound } from 'scenes/session-recordings/player/RecordingNotFound'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

export const scene: SceneExport = {
    logic: sessionRecordingDetailLogic,
    component: SessionRecordingDetail,
    paramsToProps: ({ params: { id } }): (typeof sessionRecordingDetailLogic)['props'] => ({
        id,
    }),
}

export function SessionRecordingDetail({ id }: SessionRecordingDetailLogicProps = {}): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    return (
        <div className="SessionRecordingScene">
            <PageHeader />
            {currentTeam && !currentTeam?.session_recording_opt_in ? (
                <div className="mb-4">
                    <LemonBanner type="info">
                        Session recordings are currently disabled for this project. To use this feature, please go to
                        your <Link to={`${urls.settings('project')}#recordings`}>project settings</Link> and enable it.
                    </LemonBanner>
                </div>
            ) : null}
            <div className="mt-4 flex-1">
                {id ? (
                    <SessionRecordingPlayer sessionRecordingId={id} playerKey={`${id}-detail`} />
                ) : (
                    <RecordingNotFound />
                )}
            </div>
        </div>
    )
}
