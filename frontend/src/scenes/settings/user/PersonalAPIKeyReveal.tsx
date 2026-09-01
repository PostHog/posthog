import { useState } from 'react'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

export interface PersonalAPIKeyRevealProps {
    label: string
    value: string
    /** Set when the key was rolled: the previous key's masked value, or null when it is unknown. */
    rolledFromMaskValue?: string | null
    onDone: () => void
}

export function PersonalAPIKeyReveal({
    label,
    value,
    rolledFromMaskValue,
    onDone,
}: PersonalAPIKeyRevealProps): JSX.Element {
    const [copied, setCopied] = useState(false)
    const wasRolled = rolledFromMaskValue !== undefined

    return (
        <>
            <p className="mb-4">
                {wasRolled
                    ? `Your key "${label}" has been rolled:`
                    : `You can now use key "${label}" for authentication:`}
            </p>

            <CodeSnippet className="ph-no-capture" thing="personal API key" onCopy={() => setCopied(true)}>
                {value}
            </CodeSnippet>

            <LemonBanner type="warning" className="mt-4">
                {wasRolled && (
                    <>Your previous key{rolledFromMaskValue ? ` "${rolledFromMaskValue}"` : ''} no longer works. </>
                )}
                For security reasons the value above <em>will never be shown again</em>. Copy it now and store it
                somewhere safe.
            </LemonBanner>

            <div className="flex justify-end mt-4">
                <LemonButton
                    type="primary"
                    data-attr="personal-api-key-reveal-done"
                    onClick={() => {
                        if (copied) {
                            onDone()
                            return
                        }
                        // The value is shown once. Copy it on the primary path, and close only after
                        // it reaches the clipboard, so the person cannot dismiss an uncopied secret.
                        void copyToClipboard(value, 'personal API key').then((didCopy) => {
                            if (didCopy) {
                                setCopied(true)
                                onDone()
                            }
                        })
                    }}
                >
                    {copied ? 'Done' : 'Copy and close'}
                </LemonButton>
            </div>
        </>
    )
}
