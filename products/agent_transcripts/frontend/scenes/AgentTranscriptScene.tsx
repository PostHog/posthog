import { useValues } from 'kea'

import { QuillSurfaceContext } from 'lib/ui/QuillSurface/quillSurfaceContext'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { SubmissionReviewStatus } from '../components/SubmissionReviewStatus'
import { TranscriptLoadError } from '../components/TranscriptLoadError'
import { TranscriptPageSkeleton } from '../components/TranscriptPageSkeleton'
import { TranscriptRequestForm } from '../components/TranscriptRequestForm'
import { SubmissionStatusEnumApi } from '../generated/api.schemas'
import { agentTranscriptSceneLogic } from './agentTranscriptSceneLogic'

// A submission in one of these has an uploaded file, so the scene shows where its review stands instead of the upload.
const REVIEW_STATUSES: ReadonlySet<SubmissionStatusEnumApi | null> = new Set([
    SubmissionStatusEnumApi.Submitted,
    SubmissionStatusEnumApi.Approved,
    SubmissionStatusEnumApi.Declined,
])

// An outcome screen is only a hog and a few lines, so it sits in the middle of the scene instead of under its top edge.
const OUTCOME_CLASS = 'flex min-h-[60vh] flex-col justify-center'

export const scene: SceneExport = {
    component: AgentTranscriptScene,
    logic: agentTranscriptSceneLogic,
}

function AgentTranscriptSceneBody(): JSX.Element {
    const { submission, submissionLoadFailed, variant } = useValues(agentTranscriptSceneLogic)

    if (!submission && submissionLoadFailed) {
        return (
            <div className={OUTCOME_CLASS}>
                <TranscriptLoadError />
            </div>
        )
    }

    if (!submission) {
        return <TranscriptPageSkeleton />
    }

    if (REVIEW_STATUSES.has(submission.status)) {
        return (
            <div className={OUTCOME_CLASS}>
                <SubmissionReviewStatus submission={submission} variant={variant} />
            </div>
        )
    }

    return <TranscriptRequestForm submission={submission} variant={variant} />
}

export function AgentTranscriptScene(): JSX.Element {
    return (
        <SceneContent>
            <QuillSurfaceContext.Provider value>
                <div
                    data-quill
                    className="@container/agent-transcript mx-auto flex w-full max-w-2xl flex-col py-6 @min-[32rem]/main-content:py-10"
                >
                    <AgentTranscriptSceneBody />
                </div>
            </QuillSurfaceContext.Provider>
        </SceneContent>
    )
}
