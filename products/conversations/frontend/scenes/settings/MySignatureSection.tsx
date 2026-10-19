import { useActions, useValues } from 'kea'

import { LemonButton, LemonCard, LemonCheckbox, LemonSkeleton, LemonTextArea } from '@posthog/lemon-ui'

import { agentSignatureLogic } from './agentSignatureLogic'

const SIGNATURE_MAX_CHARS = 1000

export function MySignatureSection(): JSX.Element {
    const { signature, signatureLoading, draftText, draftIncludeProfilePicture, hasChanges } =
        useValues(agentSignatureLogic)
    const { setDraftText, setDraftIncludeProfilePicture, saveSignature } = useActions(agentSignatureLogic)

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-3 px-4 py-3">
            <div>
                <label className="font-medium">My signature</label>
                <p className="text-xs text-muted-alt mb-0">
                    Added to the end of the support emails you send from this project. Only you see and edit this
                    signature. Leave it empty to send emails without one.
                </p>
            </div>
            {signature === null && signatureLoading ? (
                <LemonSkeleton className="h-24" />
            ) : signature === null ? (
                <p className="text-xs text-danger mb-0">
                    Could not load your signature. Refresh the page to try again.
                </p>
            ) : (
                <>
                    <LemonTextArea
                        value={draftText}
                        onChange={setDraftText}
                        placeholder={'Sam Rivera\nSupport engineer'}
                        maxLength={SIGNATURE_MAX_CHARS}
                        minRows={3}
                        data-attr="support-my-signature-text"
                    />
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <LemonCheckbox
                            checked={draftIncludeProfilePicture}
                            onChange={setDraftIncludeProfilePicture}
                            label="Include my profile picture from Gravatar"
                        />
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={saveSignature}
                            loading={signatureLoading}
                            disabledReason={!hasChanges ? 'No changes to save' : undefined}
                            data-attr="support-my-signature-save"
                        >
                            Save signature
                        </LemonButton>
                    </div>
                </>
            )}
        </LemonCard>
    )
}
