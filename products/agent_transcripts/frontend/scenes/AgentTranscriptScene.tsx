import { useActions, useValues } from 'kea'

import { IconChat } from '@posthog/icons'
import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { SubmissionStatusMessage } from '../components/SubmissionStatusMessage'
import { TranscriptInstructions } from '../components/TranscriptInstructions'
import { TranscriptRequestIntro } from '../components/TranscriptRequestIntro'
import { TranscriptUpload } from '../components/TranscriptUpload'
import { SubmissionStatusEnumApi } from '../generated/api.schemas'
import { agentTranscriptSceneLogic } from './agentTranscriptSceneLogic'

const LOADING_SKELETON_ROWS = 4

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

    if (submission.status === SubmissionStatusEnumApi.Submitted) {
        return (
            <SubmissionStatusMessage title="Your transcript is in review" data-attr="agent-transcript-in-review">
                <p className="m-0">
                    The PostHog team is reviewing <strong translate="no">{submission.original_filename}</strong>, which
                    you uploaded{' '}
                    {submission.submitted_at ? <TZLabel time={submission.submitted_at} /> : <span>recently</span>}.
                </p>
                <p className="m-0">Thanks for sharing it.</p>
            </SubmissionStatusMessage>
        )
    }

    if (submission.status === SubmissionStatusEnumApi.Approved) {
        return (
            <SubmissionStatusMessage title="We approved your transcript" data-attr="agent-transcript-approved">
                <p className="m-0">
                    {variant === 'test'
                        ? 'Thanks for sharing it. Your $20 code for the PostHog merch store is on its way to your email.'
                        : 'Thanks for sharing it. It helps us improve how agents set up PostHog.'}
                </p>
            </SubmissionStatusMessage>
        )
    }

    if (submission.status === SubmissionStatusEnumApi.Declined) {
        return (
            <SubmissionStatusMessage title="We couldn't use your transcript" data-attr="agent-transcript-declined">
                {submission.review_message && <p className="m-0 whitespace-pre-wrap">{submission.review_message}</p>}
                <p className="m-0">Thanks for taking the time to share it.</p>
            </SubmissionStatusMessage>
        )
    }

    return (
        <div className="flex flex-col gap-6">
            {submission.status === SubmissionStatusEnumApi.ChangesRequested && (
                <div data-attr="agent-transcript-changes-requested">
                    <LemonBanner type="warning">
                        <p className="m-0 font-semibold">The PostHog team asked for changes</p>
                        {submission.review_message && (
                            <p className="m-0 mt-1 whitespace-pre-wrap">{submission.review_message}</p>
                        )}
                        <p className="m-0 mt-1">Make the changes, then upload the new file below.</p>
                    </LemonBanner>
                </div>
            )}
            <TranscriptRequestIntro variant={variant} retentionDays={submission.retention_days} />
            <SceneDivider />
            <SceneSection title="Which agent did you use?">
                <TranscriptInstructions />
            </SceneSection>
            <SceneDivider />
            <SceneSection title="Upload the transcript">
                <TranscriptUpload submission={submission} />
            </SceneSection>
        </div>
    )
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
