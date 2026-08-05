import { Meta } from '@storybook/react'
import { BindLogic } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { makeExperimentSessionContextItem } from '../../__mocks__/experiment_session_context'
import { recordingMetaJson } from '../../__mocks__/recording_meta'
import { sessionRecordingDataCoordinatorLogic } from '../sessionRecordingDataCoordinatorLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { PlayerMetaExperimentTags } from './PlayerMetaExperimentTags'

const meta: Meta = {
    title: 'Replay/Player Meta/Experiment Tags',
    component: PlayerMetaExperimentTags,
    parameters: {
        featureFlags: [FEATURE_FLAGS.REPLAY_EXPERIMENT_CONTEXT],
        testOptions: {
            waitForLoadersToDisappear: true,
            waitForSelector: '[data-attr=replay-experiment-context-chip]',
        },
    },
    tags: ['autodocs'],
}
export default meta

// Wrapper component that provides the required logic props. The experiment context logic is
// keyed and cached by sessionRecordingId, so each story with a different payload uses its own id.
function MockedPlayerMetaExperimentTags({ sessionRecordingId }: { sessionRecordingId: string }): JSX.Element {
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
                <PlayerMetaExperimentTags />
            </BindLogic>
        </BindLogic>
    )
}

const secondExperiment = makeExperimentSessionContextItem({
    experiment_id: 102,
    experiment_name: 'Pricing page layout',
    flag_key: 'pricing-page-layout',
    variant: 'control',
    variants_seen: ['control'],
})

export function Default(): JSX.Element {
    return <MockedPlayerMetaExperimentTags sessionRecordingId="experiment-tags-default" />
}
Default.decorators = [
    mswDecorator({
        get: {
            '/api/environments/:team_id/session_recordings/:id': recordingMetaJson,
            '/api/projects/:team_id/experiments/session_context/': {
                session_id: 'experiment-tags-default',
                results: [makeExperimentSessionContextItem(), secondExperiment],
            },
        },
    }),
]

// Only the first two experiments render as tags; the rest collapse into a "+N" overflow tag.
export function Overflow(): JSX.Element {
    return <MockedPlayerMetaExperimentTags sessionRecordingId="experiment-tags-overflow" />
}
Overflow.decorators = [
    mswDecorator({
        get: {
            '/api/environments/:team_id/session_recordings/:id': recordingMetaJson,
            '/api/projects/:team_id/experiments/session_context/': {
                session_id: 'experiment-tags-overflow',
                results: [
                    makeExperimentSessionContextItem(),
                    secondExperiment,
                    makeExperimentSessionContextItem({
                        experiment_id: 103,
                        experiment_name: 'Onboarding checklist',
                        flag_key: 'onboarding-checklist',
                    }),
                    makeExperimentSessionContextItem({
                        experiment_id: 104,
                        experiment_name: 'Signup form length',
                        flag_key: 'signup-form-length',
                    }),
                ],
            },
        },
    }),
]

export function MultipleVariantsWarning(): JSX.Element {
    return <MockedPlayerMetaExperimentTags sessionRecordingId="experiment-tags-warning" />
}
MultipleVariantsWarning.decorators = [
    mswDecorator({
        get: {
            '/api/environments/:team_id/session_recordings/:id': recordingMetaJson,
            '/api/projects/:team_id/experiments/session_context/': {
                session_id: 'experiment-tags-warning',
                results: [
                    makeExperimentSessionContextItem({
                        variants_seen: ['control', 'test'],
                        multiple_variants: true,
                    }),
                ],
            },
        },
    }),
]
