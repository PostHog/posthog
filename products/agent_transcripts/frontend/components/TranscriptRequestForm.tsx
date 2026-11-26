import { useValues } from 'kea'

import type { CustomerSubmissionStateApi } from '../generated/api.schemas'
import { SubmissionStatusEnumApi } from '../generated/api.schemas'
import type { AgentTranscriptRequestVariant } from '../logics/agentTranscriptVariant'
import { formatExtensions, formatMegabytes } from '../logics/transcriptUploadErrors'
import { agentTranscriptSceneLogic } from '../scenes/agentTranscriptSceneLogic'
import { TranscriptAgentHog } from './TranscriptAgentHog'
import { TranscriptAgentPicker } from './TranscriptAgentPicker'
import { TranscriptChangesRequested } from './TranscriptChangesRequested'
import { TranscriptFileNotes } from './TranscriptFileNotes'
import { AgentPickerHog } from './transcriptHogs'
import { TranscriptInstructions } from './TranscriptInstructions'
import { TranscriptRequestIntro } from './TranscriptRequestIntro'
import { TranscriptStep } from './TranscriptStep'
import { TranscriptUpload } from './TranscriptUpload'
import { TranscriptUploadHog } from './TranscriptUploadHog'

export interface TranscriptRequestFormProps {
    submission: CustomerSubmissionStateApi
    variant: AgentTranscriptRequestVariant | null
}

/** The request and the upload, for an organization that has not uploaded yet or was asked for changes. */
export function TranscriptRequestForm({ submission, variant }: TranscriptRequestFormProps): JSX.Element {
    const { selectedAgent } = useValues(agentTranscriptSceneLogic)

    return (
        <div className="flex flex-col gap-8">
            {submission.status === SubmissionStatusEnumApi.ChangesRequested ? (
                <TranscriptChangesRequested reviewMessage={submission.review_message} variant={variant} />
            ) : (
                <TranscriptRequestIntro variant={variant} />
            )}
            <div className="flex flex-col gap-3">
                <TranscriptStep
                    number={1}
                    title="Choose your agent"
                    description="How you get the transcript depends on the agent."
                    hog={<AgentPickerHog className="size-full" loading="eager" />}
                >
                    <TranscriptAgentPicker />
                </TranscriptStep>
                <TranscriptStep
                    number={2}
                    title="Get the transcript"
                    description="Save the conversation where the agent set up PostHog as a file."
                    hog={<TranscriptAgentHog agent={selectedAgent} />}
                >
                    <TranscriptInstructions />
                </TranscriptStep>
                <TranscriptStep
                    number={3}
                    title="Upload the transcript"
                    description={
                        <>
                            A {formatExtensions(submission.allowed_extensions)} file, up to{' '}
                            {formatMegabytes(submission.max_size_bytes)}. We reject files that contain API keys or
                            tokens.
                        </>
                    }
                    hog={<TranscriptUploadHog />}
                >
                    <TranscriptUpload submission={submission} />
                </TranscriptStep>
            </div>
            <TranscriptFileNotes retentionDays={submission.retention_days} />
        </div>
    )
}
