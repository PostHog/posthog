import { useValues } from 'kea'

import { IconDocument } from '@posthog/icons'
import { Item, ItemContent, ItemDescription, ItemMedia, ItemTitle, Progress } from '@posthog/quill'

import { TranscriptUploadStep, agentTranscriptSceneLogic } from '../scenes/agentTranscriptSceneLogic'

const PERCENT = 100

const STEP_LABELS: Record<TranscriptUploadStep, string> = {
    starting: 'Preparing the upload',
    sending: 'Uploading',
    checking: 'Checking the file',
}

export interface TranscriptUploadProgressProps {
    step: TranscriptUploadStep
}

export function TranscriptUploadProgress({ step }: TranscriptUploadProgressProps): JSX.Element {
    const { uploadProgress, uploadFileName } = useValues(agentTranscriptSceneLogic)

    const percent = Math.round(uploadProgress * PERCENT)

    return (
        <Item variant="outline" aria-live="polite" data-attr="agent-transcript-upload-progress">
            <ItemMedia variant="icon">
                <IconDocument />
            </ItemMedia>
            <ItemContent className="min-w-0 gap-2">
                <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                    <ItemTitle className="min-w-0 truncate" translate="no">
                        {uploadFileName}
                    </ItemTitle>
                    <ItemDescription className="quill-shimmer">
                        {step === 'sending' ? `${STEP_LABELS[step]} ${percent}%` : STEP_LABELS[step]}
                    </ItemDescription>
                </div>
                <Progress value={step === 'checking' ? PERCENT : percent} aria-label={STEP_LABELS[step]} />
            </ItemContent>
        </Item>
    )
}
