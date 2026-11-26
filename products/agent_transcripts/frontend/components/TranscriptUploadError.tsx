import { Callout, CalloutContent, CalloutDescription, CalloutIcon } from '@posthog/quill'

import {
    CONTAINS_SECRET_CODE,
    TranscriptUploadError as TranscriptUploadErrorType,
} from '../logics/transcriptUploadErrors'

export interface TranscriptUploadErrorProps {
    error: TranscriptUploadErrorType
}

export function TranscriptUploadError({ error }: TranscriptUploadErrorProps): JSX.Element {
    return (
        <Callout tone="destructive" role="alert" data-attr="agent-transcript-upload-error">
            <CalloutIcon />
            <CalloutContent>
                <CalloutDescription className="flex flex-col gap-1">
                    <p className="m-0">{error.detail}</p>
                    {error.code === CONTAINS_SECRET_CODE && (
                        <p className="m-0">
                            Replace each key or token in the file with [REDACTED]. You can ask your agent to do it for
                            you.
                        </p>
                    )}
                </CalloutDescription>
            </CalloutContent>
        </Callout>
    )
}
