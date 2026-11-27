import { useValues } from 'kea'

import { CONTAINS_SECRET_CODE } from '../logics/transcriptUploadErrors'
import { agentTranscriptSceneLogic } from '../scenes/agentTranscriptSceneLogic'
import { CheckingHog, SecretFoundHog, SendingHog, UploadHog } from './transcriptHogs'

/** The hedgehog for the upload step, which follows the upload: waiting, sending, checking, or a secret found. */
export function TranscriptUploadHog(): JSX.Element {
    const { uploadStep, uploadError } = useValues(agentTranscriptSceneLogic)

    if (uploadStep === 'checking') {
        return <CheckingHog className="size-full" loading="eager" />
    }

    if (uploadStep) {
        return <SendingHog className="size-full" loading="eager" />
    }

    if (uploadError?.code === CONTAINS_SECRET_CODE) {
        return <SecretFoundHog className="size-full" loading="eager" />
    }

    return <UploadHog className="size-full" loading="eager" />
}
