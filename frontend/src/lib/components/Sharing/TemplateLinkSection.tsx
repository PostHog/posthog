import posthog from 'posthog-js'
import { useState } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TitleWithIcon } from 'lib/components/TitleWithIcon'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconLink } from 'lib/lemon-ui/icons'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

interface TemplateLinkSectionProps {
    templateLink: string
    onShortenLink?: () => void
    showShortenButton?: boolean
    heading?: string
    tooltip?: string
    piiWarning?: string
    copyButtonLabel?: string
}

export function TemplateLinkSection({
    templateLink,
    onShortenLink,
    showShortenButton = false,
    heading,
    tooltip = 'Share this link to let others create a copy of this insight with the same configuration.',
    piiWarning = 'Be aware that you may be sharing sensitive data if contained in your event, property names or filters.',
    copyButtonLabel = 'Copy link',
}: TemplateLinkSectionProps): JSX.Element {
    const [copied, setCopied] = useState(false)

    const isMultiline = templateLink.includes('\n')
    const rows = Math.min(12, Math.max(3, templateLink.split('\n').length))

    const handleCopyLink = async (): Promise<void> => {
        try {
            await copyToClipboard(templateLink)
            setCopied(true)
            setTimeout(() => setCopied(false), 2000)
        } catch (e) {
            posthog.captureException(new Error('unexpected template link clipboard error: ' + (e as Error).message))
        }
    }

    return (
        <div className="deprecated-space-y-2">
            {typeof heading === 'string' && heading && (
                <TitleWithIcon
                    icon={
                        tooltip ? (
                            <Tooltip title={tooltip}>
                                <IconInfo />
                            </Tooltip>
                        ) : (
                            <span />
                        )
                    }
                >
                    <b>{heading}</b>
                </TitleWithIcon>
            )}
            {piiWarning && <p className="text-muted mb-1">{piiWarning}</p>}
            <div className="flex gap-2 items-start">
                <div className="flex-1">
                    {isMultiline ? (
                        <textarea
                            value={templateLink}
                            readOnly
                            rows={rows}
                            className="w-full px-3 py-2 text-sm border rounded bg-bg-light font-mono"
                            onClick={(e) => (e.target as HTMLTextAreaElement).select()}
                        />
                    ) : (
                        <input
                            type="text"
                            value={templateLink}
                            readOnly
                            className="w-full px-3 py-2 text-sm border rounded bg-bg-light"
                            onClick={(e) => (e.target as HTMLInputElement).select()}
                        />
                    )}
                </div>
                <LemonButton
                    type="secondary"
                    onClick={() => {
                        void handleCopyLink()
                    }}
                    icon={<IconLink />}
                >
                    {copied ? 'Copied!' : copyButtonLabel}
                </LemonButton>
            </div>

            {showShortenButton && (
                <>
                    <div className="flex items-center justify-between">
                        <div>
                            <div className="flex items-center gap-2">
                                <LemonButton type="secondary" onClick={onShortenLink} disabled={!onShortenLink}>
                                    Shorten URL
                                </LemonButton>
                            </div>
                        </div>
                    </div>
                </>
            )}
        </div>
    )
}
