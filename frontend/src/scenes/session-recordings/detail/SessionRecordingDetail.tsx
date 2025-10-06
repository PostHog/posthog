import './SessionRecordingScene.scss'

import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import {
    SessionRecordingDetailLogicProps,
    sessionRecordingDetailLogic,
} from 'scenes/session-recordings/detail/sessionRecordingDetailLogic'
import { RecordingNotFound } from 'scenes/session-recordings/player/RecordingNotFound'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

export const scene: SceneExport<SessionRecordingDetailLogicProps> = {
    logic: sessionRecordingDetailLogic,
    component: SessionRecordingDetail,
    paramsToProps: ({ params: { id } }) => ({
        id,
    }),
    settingSectionId: 'environment-replay',
}

export function SessionRecordingDetail({ id }: SessionRecordingDetailLogicProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const settingLevel = featureFlags[FEATURE_FLAGS.ENVIRONMENTS] ? 'environment' : 'project'

    return (
        <div className="SessionRecordingScene">
            {currentTeam && !currentTeam?.session_recording_opt_in ? (
                <div className="mb-4">
                    <LemonBanner type="info">
                        Session recordings are currently disabled for this {settingLevel}. To use this feature, please
                        go to your <Link to={`${urls.settings('project')}#recordings`}>project settings</Link> and
                        enable it.
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
