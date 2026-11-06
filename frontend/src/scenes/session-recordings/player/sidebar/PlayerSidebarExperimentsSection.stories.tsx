import { Meta } from '@storybook/react'
import { BindLogic } from 'kea'
import { router } from 'kea-router'
import { delay } from 'msw'

import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import {
    ENROLLED_CURRENT_EXPERIMENT_ID,
    experimentSessionContextEnrolledCurrentResponse,
    experimentSessionContextResponse,
    makeExperimentSessionContextItem,
} from '../../__mocks__/experiment_session_context'
import { recordingMetaJson } from '../../__mocks__/recording_meta'
import { sessionRecordingDataCoordinatorLogic } from '../sessionRecordingDataCoordinatorLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { PlayerSidebarExperimentsSection } from './PlayerSidebarExperimentsSection'

const meta: Meta = {
    title: 'Replay/Overview Tab/Experiments',
    component: PlayerSidebarExperimentsSection,
    parameters: {
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

// The experiment the viewer arrived from has no exposure event in this session. Pinning takes it out
// of the enrolled group, so the row itself has to say it wasn't exposed here.
export function CurrentExperimentNotExposed(): JSX.Element {
    router.actions.push(urls.experiment(ENROLLED_CURRENT_EXPERIMENT_ID))
    return <MockedPlayerSidebarExperimentsSection sessionRecordingId="experiment-context-enrolled-current" />
}
CurrentExperimentNotExposed.parameters = {
    testOptions: {
        waitForLoadersToDisappear: true,
        waitForSelector: '[data-attr=replay-experiment-context-not-exposed]',
    },
}
CurrentExperimentNotExposed.decorators = [
    mswDecorator({
        get: {
            '/api/environments/:team_id/session_recordings/:id': recordingMetaJson,
            '/api/projects/:team_id/experiments/session_context/': experimentSessionContextEnrolledCurrentResponse,
        },
    }),
]

// The recording window resolves to 14:46:20–14:46:32 from the meta mock. One exposure fired before
// the first frame, one inside, one after the last frame, so the story snapshots the signed offsets
// (-, none, +) that the out-of-window rows now render.
export function ExposureOutsideWindow(): JSX.Element {
    return <MockedPlayerSidebarExperimentsSection sessionRecordingId="experiment-context-out-of-window" />
}
ExposureOutsideWindow.parameters = {
    testOptions: {
        waitForLoadersToDisappear: true,
        waitForSelector: '[data-attr=replay-experiment-context-jump-to-first-exposure]',
    },
}
ExposureOutsideWindow.decorators = [
    mswDecorator({
        get: {
            '/api/environments/:team_id/session_recordings/:id': recordingMetaJson,
            '/api/projects/:team_id/experiments/session_context/': {
                session_id: 'experiment-context-out-of-window',
                results: [
                    makeExperimentSessionContextItem({
                        experiment_id: 301,
                        experiment_name: 'Exposed before first frame',
                        flag_key: 'exposed-before-first-frame',
                        first_exposure_timestamp: '2023-05-01T14:45:57.000000Z',
                    }),
                    makeExperimentSessionContextItem({
                        experiment_id: 302,
                        experiment_name: 'Exposed in window',
                        flag_key: 'exposed-in-window',
                        first_exposure_timestamp: '2023-05-01T14:46:26.000000Z',
                    }),
                    makeExperimentSessionContextItem({
                        experiment_id: 303,
                        experiment_name: 'Exposed after last frame',
                        flag_key: 'exposed-after-last-frame',
                        first_exposure_timestamp: '2023-05-01T14:47:00.000000Z',
                    }),
                ],
            },
        },
    }),
]

// While the context request is in flight the box shows a skeleton placeholder — but only when the
// viewer arrived from an experiment's recordings tab, so the route is put on /experiments/<id>
// first. The mocked request never resolves, holding the section in its loading state.
export function Loading(): JSX.Element {
    router.actions.push(urls.experiment(123))
    return <MockedPlayerSidebarExperimentsSection sessionRecordingId="experiment-context-loading" />
}
Loading.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
        waitForSelector: '[data-attr=replay-experiment-context-overview-loading]',
    },
}
Loading.decorators = [
    mswDecorator({
        get: {
            '/api/environments/:team_id/session_recordings/:id': recordingMetaJson,
            '/api/projects/:team_id/experiments/session_context/': async () => {
                await delay('infinite')
                return [200, { session_id: 'experiment-context-loading', results: [] }]
            },
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
