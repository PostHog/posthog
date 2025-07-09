import { IconInfo } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { TitleWithIcon } from 'lib/components/TitleWithIcon'
import { IconLink } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import posthog from 'posthog-js'
import { useState } from 'react'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { useAsyncHandler } from 'lib/hooks/useAsyncHandler'

interface TemplateLinkSectionProps {
    templateLink: string
    onShortenLink?: () => void
    showShortenButton?: boolean
    heading?: string
    tooltip?: string
    piiWarning?: string
    // New props for shortlink functionality
    insightId?: number
    enableShortlinkCreation?: boolean
}

interface ShortlinkData {
    short_url: string
    short_code: string
    original_url: string
    created_at: string
}

export function TemplateLinkSection({
    templateLink,
    onShortenLink,
    showShortenButton = false,
    heading,
    tooltip = 'Share this link to let others create a copy of this insight with the same configuration.',
    piiWarning = 'Be aware that you may be sharing sensitive data if contained in your event, property names or filters.',
    insightId,
    enableShortlinkCreation = false,
}: TemplateLinkSectionProps): JSX.Element {
    const [copied, setCopied] = useState(false)
    const [shortlinkData, setShortlinkData] = useState<ShortlinkData | null>(null)
    const [shortlinkError, setShortlinkError] = useState<string | null>(null)

    const handleCopyLink = async (linkToCopy: string): Promise<void> => {
        try {
            await copyToClipboard(linkToCopy)
            setCopied(true)
            setTimeout(() => setCopied(false), 2000)
        } catch (e) {
            posthog.captureException(new Error('unexpected template link clipboard error: ' + (e as Error).message))
        }
    }

    const { loading: creatingShortlink, onEvent: handleCreateShortlink } = useAsyncHandler(async () => {
        if (!insightId) {
            lemonToast.error('Cannot create shortlink: missing insight ID')
            return
        }

        try {
            setShortlinkError(null)
            const response = await api.insights.createShortlink(insightId)
            setShortlinkData(response)
            posthog.capture('shortlink_created', {
                insight_id: insightId,
                short_code: response.short_code,
            })
            lemonToast.success('Shortlink created successfully!')
        } catch (error: any) {
            const errorMessage = error?.detail || error?.message || 'Failed to create shortlink'
            setShortlinkError(errorMessage)
            lemonToast.error(errorMessage)
            posthog.capture('shortlink_creation_failed', {
                insight_id: insightId,
                error: errorMessage,
            })
        }
    })

    const displayLink = shortlinkData?.short_url || templateLink
    const isShortlink = !!shortlinkData

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

            {/* Main link input and copy button */}
            <div className="flex gap-2">
                <div className="flex-1">
                    <input
                        type="text"
                        value={displayLink}
                        readOnly
                        className="w-full px-3 py-2 text-sm border rounded bg-bg-light"
                        onClick={(e) => (e.target as HTMLInputElement).select()}
                    />
                </div>
                <LemonButton
                    type="secondary"
                    onClick={() => {
                        void handleCopyLink(displayLink)
                    }}
                    icon={<IconLink />}
                >
                    {copied ? 'Copied!' : 'Copy link'}
                </LemonButton>
            </div>

            {/* Shortlink section */}
            {(enableShortlinkCreation || showShortenButton) && (
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        {enableShortlinkCreation && insightId && !shortlinkData ? (
                            <LemonButton
                                type="secondary"
                                onClick={handleCreateShortlink}
                                loading={creatingShortlink}
                                disabled={creatingShortlink}
                            >
                                Shorten URL
                            </LemonButton>
                        ) : showShortenButton ? (
                            <LemonButton type="secondary" onClick={onShortenLink} disabled={!onShortenLink}>
                                Shorten URL
                            </LemonButton>
                        ) : null}

                        {isShortlink && (
                            <span className="text-sm text-muted">
                                Short URL created • {new Date(shortlinkData.created_at).toLocaleString()}
                            </span>
                        )}
                    </div>
                </div>
            )}

            {/* Error display */}
            {shortlinkError && (
                <div className="text-sm text-danger bg-danger-highlight px-2 py-1 rounded">{shortlinkError}</div>
            )}

            {/* Original link when showing shortlink */}
            {isShortlink && (
                <div className="deprecated-space-y-1">
                    <div className="text-xs text-muted font-medium">Original template link:</div>
                    <div className="flex gap-2">
                        <div className="flex-1">
                            <input
                                type="text"
                                value={templateLink}
                                readOnly
                                className="w-full px-2 py-1 text-xs border rounded bg-bg-light text-muted"
                                onClick={(e) => (e.target as HTMLInputElement).select()}
                            />
                        </div>
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            onClick={() => {
                                void handleCopyLink(templateLink)
                            }}
                            icon={<IconLink />}
                        >
                            Copy
                        </LemonButton>
                    </div>
                </div>
            )}
        </div>
    )
}
