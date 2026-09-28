import posthog from 'posthog-js'

import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

interface SharingLinkFieldProps {
    link: string
    copyLabel: string
    copyDescription: string
    'data-attr': string
}

export function SharingLinkField({
    link,
    copyLabel,
    copyDescription,
    'data-attr': dataAttr,
}: SharingLinkFieldProps): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-2">
            <LemonInput
                className="min-w-40 flex-1"
                value={link}
                readOnly
                aria-label={copyDescription}
                onFocus={(e) => e.target.select()}
            />
            <LemonButton
                data-attr={dataAttr}
                type="primary"
                icon={<IconCopy />}
                onClick={() => {
                    // TRICKY: there's a chance this was sending useless errors to error tracking
                    // even when it succeeded, so we're explicitly ignoring the promise success
                    // and naming the error when reported to error tracking - @pauldambra
                    copyToClipboard(link, copyDescription).catch((e) =>
                        posthog.captureException(new Error('unexpected sharing modal clipboard error: ' + e.message))
                    )
                }}
            >
                {copyLabel}
            </LemonButton>
        </div>
    )
}
