import { useActions, useValues } from 'kea'

import { IconUpload } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import type { CustomerSubmissionStateApi } from '../generated/api.schemas'
import { CONTAINS_SECRET_CODE, formatExtensions, formatMegabytes } from '../logics/transcriptUploadErrors'
import { TranscriptUploadStep, agentTranscriptSceneLogic } from '../scenes/agentTranscriptSceneLogic'

const PERCENT = 100

const STEP_LABELS: Record<TranscriptUploadStep, string> = {
    starting: 'Preparing the upload',
    sending: 'Uploading',
    checking: 'Checking the file',
}

export interface TranscriptUploadProps {
    submission: CustomerSubmissionStateApi
}

export function TranscriptUpload({ submission }: TranscriptUploadProps): JSX.Element {
    const { selectedAgent, uploadStep, uploadProgress, uploadFileName, uploadError } =
        useValues(agentTranscriptSceneLogic)
    const { uploadTranscript } = useActions(agentTranscriptSceneLogic)

    const disabledReason = !selectedAgent ? 'Choose the agent you used first' : null
    const percent = Math.round(uploadProgress * PERCENT)

    return (
        <div className="flex flex-col gap-3">
            {uploadStep ? (
                <div
                    className="flex flex-col gap-2 rounded border border-primary p-4"
                    aria-live="polite"
                    data-attr="agent-transcript-upload-progress"
                >
                    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                        <span className="min-w-0 truncate font-semibold" translate="no">
                            {uploadFileName}
                        </span>
                        <span className="text-secondary">
                            {uploadStep === 'sending'
                                ? `${STEP_LABELS[uploadStep]} ${percent}%`
                                : STEP_LABELS[uploadStep]}
                        </span>
                    </div>
                    <LemonProgress percent={uploadStep === 'checking' ? PERCENT : percent} />
                </div>
            ) : (
                <LemonFileInput
                    accept={submission.allowed_extensions.join(',')}
                    multiple={false}
                    showUploadedFiles={false}
                    disabledReason={disabledReason}
                    onChange={(files) => {
                        if (files[0]) {
                            uploadTranscript(files[0])
                        }
                    }}
                    callToAction={
                        <div
                            className="flex w-full flex-col items-center gap-2 rounded border border-dashed border-primary p-6 text-center"
                            data-attr="agent-transcript-dropzone"
                        >
                            <IconUpload className="text-3xl text-secondary" />
                            <span className="text-primary">Drop the transcript file here</span>
                            <LemonButton type="secondary" size="small" disabledReason={disabledReason}>
                                Choose file
                            </LemonButton>
                        </div>
                    }
                />
            )}
            <p className="m-0 text-xs text-secondary">
                A {formatExtensions(submission.allowed_extensions)} file, up to{' '}
                {formatMegabytes(submission.max_size_bytes)}. We reject files that contain API keys or tokens.
            </p>
            {uploadError && (
                <div role="alert" data-attr="agent-transcript-upload-error">
                    <LemonBanner type="error">
                        <p className="m-0">{uploadError.detail}</p>
                        {uploadError.code === CONTAINS_SECRET_CODE && (
                            <p className="m-0 mt-1">
                                Replace each key or token in the file with [REDACTED]. You can ask your agent to do it
                                for you.
                            </p>
                        )}
                    </LemonBanner>
                </div>
            )}
        </div>
    )
}
