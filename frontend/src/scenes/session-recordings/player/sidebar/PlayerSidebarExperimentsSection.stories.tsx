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

// The section renders nothing when the session saw no experiments — only the caption should
// be visible. The caption also gives the snapshot runner a visible element to screenshot,
// which a fully empty story lacks.
export function Empty(): JSX.Element {
    return (
        <div className="flex flex-col gap-2 w-80">
            <div className="text-xs text-secondary">Nothing should render below this caption:</div>
            <MockedPlayerSidebarExperimentsSection sessionRecordingId="experiment-context-empty" />
        </div>
    )
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
