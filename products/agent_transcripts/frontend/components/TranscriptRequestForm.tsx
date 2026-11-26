import { LemonBanner } from '@posthog/lemon-ui'

import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'

import type { CustomerSubmissionStateApi } from '../generated/api.schemas'
import { SubmissionStatusEnumApi } from '../generated/api.schemas'
import type { AgentTranscriptRequestVariant } from '../logics/agentTranscriptVariant'
import { TranscriptInstructions } from './TranscriptInstructions'
import { TranscriptRequestIntro } from './TranscriptRequestIntro'
import { TranscriptUpload } from './TranscriptUpload'

export interface TranscriptRequestFormProps {
    submission: CustomerSubmissionStateApi
    variant: AgentTranscriptRequestVariant | null
}

/** The request and the upload, for an organization that has not uploaded yet or was asked for changes. */
export function TranscriptRequestForm({ submission, variant }: TranscriptRequestFormProps): JSX.Element {
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
