import { useActions, useValues } from 'kea'

import { IconUpload } from '@posthog/icons'
import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle, cn } from '@posthog/quill'

import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'

import type { CustomerSubmissionStateApi } from '../generated/api.schemas'
import { agentTranscriptSceneLogic } from '../scenes/agentTranscriptSceneLogic'
import { TranscriptUploadError } from './TranscriptUploadError'
import { TranscriptUploadProgress } from './TranscriptUploadProgress'

const NO_AGENT_REASON = 'Choose the agent you used first.'

export interface TranscriptUploadProps {
    submission: CustomerSubmissionStateApi
}

export function TranscriptUpload({ submission }: TranscriptUploadProps): JSX.Element {
    const { selectedAgent, uploadStep, uploadError } = useValues(agentTranscriptSceneLogic)
    const { uploadTranscript } = useActions(agentTranscriptSceneLogic)

    const disabledReason = !selectedAgent ? NO_AGENT_REASON : null

    return (
        <>
            {uploadError && <TranscriptUploadError error={uploadError} />}
            {uploadStep ? (
                <TranscriptUploadProgress step={uploadStep} />
            ) : (
                // LemonFileInput only supplies the hidden input and the drag and drop handling; the drop area is quill.
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
                        <Empty
                            className={cn('w-full text-foreground', disabledReason && 'opacity-60')}
                            data-attr="agent-transcript-dropzone"
                        >
                            <EmptyHeader>
                                <EmptyMedia variant="icon">
                                    <IconUpload />
                                </EmptyMedia>
                                <EmptyTitle>Drop the transcript file here</EmptyTitle>
                                {disabledReason && <EmptyDescription>{disabledReason}</EmptyDescription>}
                            </EmptyHeader>
                            <EmptyContent>
                                <Button variant="outline" disabledReason={disabledReason}>
                                    Choose file
                                </Button>
                            </EmptyContent>
                        </Empty>
                    }
                />
            )}
        </>
    )
}
