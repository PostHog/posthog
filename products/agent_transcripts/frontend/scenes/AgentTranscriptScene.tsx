import { useActions, useValues } from 'kea'

import { IconChat } from '@posthog/icons'
import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { SubmissionReviewStatus } from '../components/SubmissionReviewStatus'
import { TranscriptRequestForm } from '../components/TranscriptRequestForm'
import { SubmissionStatusEnumApi } from '../generated/api.schemas'
import { agentTranscriptSceneLogic } from './agentTranscriptSceneLogic'

const LOADING_SKELETON_ROWS = 4

// A submission in one of these has an uploaded file, so the scene shows where its review stands instead of the upload.
const REVIEW_STATUSES: ReadonlySet<SubmissionStatusEnumApi | null> = new Set([
    SubmissionStatusEnumApi.Submitted,
    SubmissionStatusEnumApi.Approved,
    SubmissionStatusEnumApi.Declined,
])

export const scene: SceneExport = {
    component: AgentTranscriptScene,
    logic: agentTranscriptSceneLogic,
}

function AgentTranscriptSceneBody(): JSX.Element {
    const { submission, submissionLoadFailed, variant } = useValues(agentTranscriptSceneLogic)
    const { loadSubmission } = useActions(agentTranscriptSceneLogic)

    if (!submission && submissionLoadFailed) {
        return (
            <LemonBanner type="error" action={{ children: 'Try again', onClick: loadSubmission }}>
                Couldn't load your organization's transcript. Check your connection, then try again.
            </LemonBanner>
        )
    }

    if (!submission) {
        return (
            <div className="flex flex-col gap-3" data-attr="agent-transcript-loading">
                <LemonSkeleton repeat={LOADING_SKELETON_ROWS} />
            </div>
        )
    }

    if (REVIEW_STATUSES.has(submission.status)) {
        return <SubmissionReviewStatus submission={submission} variant={variant} />
    }

    return <TranscriptRequestForm submission={submission} variant={variant} />
}

export function AgentTranscriptScene(): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.AgentTranscript].name}
                resourceType={{ type: 'default_icon_type', forceIcon: <IconChat /> }}
            />
            <div className="max-w-3xl">
                <AgentTranscriptSceneBody />
            </div>
        </SceneContent>
    )
}
