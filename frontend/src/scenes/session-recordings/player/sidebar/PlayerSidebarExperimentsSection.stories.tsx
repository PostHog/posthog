import { Meta } from '@storybook/react'
import { BindLogic } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { experimentSessionContextResponse } from '../../__mocks__/experiment_session_context'
import { recordingMetaJson } from '../../__mocks__/recording_meta'
import { sessionRecordingDataCoordinatorLogic } from '../sessionRecordingDataCoordinatorLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { PlayerSidebarExperimentsSection } from './PlayerSidebarExperimentsSection'

const meta: Meta = {
    title: 'Replay/Overview Tab/Experiments',
    component: PlayerSidebarExperimentsSection,
    parameters: {
        featureFlags: [FEATURE_FLAGS.REPLAY_EXPERIMENT_CONTEXT],
        testOptions: {
            waitForLoadersToDisappear: true,
        },
    },
    tags: ['autodocs'],
}
export default meta

// Wrapper component that provides the required logic props. The experiment context logic is
// keyed and cached by sessionRecordingId, so each story with a different payload uses its own id.
function MockedPlayerSidebarExperimentsSection({ sessionRecordingId }: { sessionRecordingId: string }): JSX.Element {
    return (
        <BindLogic
            logic={sessionRecordingDataCoordinatorLogic}
            props={{
                sessionRecordingId,
                playerKey: 'story-template',
            }}
        >
            <BindLogic
                logic={sessionRecordingPlayerLogic}
                props={{
                    sessionRecordingId,
                    playerKey: 'story-template',
                }}
            >
                <div className="w-80">
                    <PlayerSidebarExperimentsSection />
                </div>
            </BindLogic>
        </BindLogic>
    )
}

export function Default(): JSX.Element {
    return <MockedPlayerSidebarExperimentsSection sessionRecordingId="experiment-context-session" />
}
Default.parameters = {
    testOptions: {
        waitForLoadersToDisappear: true,
        waitForSelector: '[data-attr=replay-experiment-context-overview]',
    },
}
Default.decorators = [
    mswDecorator({
        get: {
            '/api/environments/:team_id/session_recordings/:id': recordingMetaJson,
            '/api/projects/:team_id/experiments/session_context/': experimentSessionContextResponse,
        },
    }),
]

// The section renders nothing when the session saw no experiments — the snapshot should stay blank.
export function Empty(): JSX.Element {
    return <MockedPlayerSidebarExperimentsSection sessionRecordingId="experiment-context-empty" />
}
Empty.decorators = [
    mswDecorator({
        get: {
            '/api/environments/:team_id/session_recordings/:id': recordingMetaJson,
            '/api/projects/:team_id/experiments/session_context/': {
                session_id: 'experiment-context-empty',
                results: [],
            },
        },
    }),
]
