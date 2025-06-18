import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { IconLink } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import posthog from 'posthog-js'
import { useState } from 'react'

interface TemplateLinkSectionProps {
    templateLink: string
    onShortenLink?: () => void
    showShortenButton?: boolean
}

export function TemplateLinkSection({
    templateLink,
    onShortenLink,
    showShortenButton = true,
}: TemplateLinkSectionProps): JSX.Element {
    const [copied, setCopied] = useState(false)

    const handleCopyLink = async (): Promise<void> => {
        try {
            await copyToClipboard(templateLink, templateLink)
            setCopied(true)
            setTimeout(() => setCopied(false), 2000)
        } catch (e) {
            posthog.captureException(new Error('unexpected template link clipboard error: ' + (e as Error).message))
        }
    }

    return (
        <div className="deprecated-space-y-2">
            <h3>Template link</h3>
            <p className="text-muted">
                Share this link to let others create a copy of this insight with the same configuration.
            </p>

            <div className="flex gap-2">
                <div className="flex-1">
                    <input
                        type="text"
                        value={templateLink}
                        readOnly
                        className="w-full px-3 py-2 text-sm border rounded bg-bg-light"
                        onClick={(e) => (e.target as HTMLInputElement).select()}
                    />
                </div>
                <LemonButton
                    type="secondary"
                    onClick={() => {
                        void handleCopyLink()
                    }}
                    icon={<IconLink />}
                >
                    {copied ? 'Copied!' : 'Copy link'}
                </LemonButton>
            </div>

            {showShortenButton && (
                <>
                    <LemonDivider />
                    <div className="flex items-center justify-between">
                        <div>
                            <LemonButton type="secondary" onClick={onShortenLink} disabled={!onShortenLink}>
                                Create shortlink
                            </LemonButton>
                            {!onShortenLink && (
                                <Tooltip title="Shortlink creation coming soon">
                                    <span className="ml-2 text-muted text-sm">(Coming soon)</span>
                                </Tooltip>
                            )}
                        </div>
                    </div>
                </>
            )}
        </div>
    )
}
