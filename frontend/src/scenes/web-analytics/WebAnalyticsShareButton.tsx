import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useRef, useState } from 'react'

import { IconCheck, IconCopy, IconShare } from '@posthog/icons'
import { LemonButton, Popover } from '@posthog/lemon-ui'

import { IconLink } from 'lib/lemon-ui/icons'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { shareNudgeLogic } from './shareNudgeLogic'

interface WebAnalyticsShareButtonProps {
    // Where the click originated, for analytics.
    source: string
    // Read lazily on each render so the copied link always reflects the current URL and filters.
    getShareUrl: () => string
}

export function WebAnalyticsShareButton({ source, getShareUrl }: WebAnalyticsShareButtonProps): JSX.Element {
    const { emphasizeShareButton } = useValues(shareNudgeLogic)
    const [isOpen, setIsOpen] = useState(false)
    const [copied, setCopied] = useState(false)
    const copiedTimeout = useRef<ReturnType<typeof setTimeout> | null>(null)

    const shareUrl = getShareUrl()

    const toggleOpen = (): void => {
        setCopied(false)
        setIsOpen((prev) => !prev)
    }

    const handleCopy = (): void => {
        void copyToClipboard(shareUrl, 'link')
        posthog.capture('web analytics share link copied', { source })
        // Reflect the copy inline, so a rapid re-click still gives visible feedback even when the toast is deduped.
        setCopied(true)
        if (copiedTimeout.current) {
            clearTimeout(copiedTimeout.current)
        }
        copiedTimeout.current = setTimeout(() => setCopied(false), 2000)
    }

    return (
        <Popover
            visible={isOpen}
            onClickOutside={() => setIsOpen(false)}
            placement="bottom-end"
            overlay={
                <div className="p-2 w-80 flex flex-col gap-2">
                    <div className="text-xs font-semibold text-muted uppercase">Share this view</div>
                    <p className="text-xs text-muted m-0">
                        Copy a link to these web analytics filters. Anyone with access to the project can open it.
                    </p>
                    <div className="flex items-center gap-2">
                        <div
                            className="flex-1 min-w-0 rounded border bg-surface-secondary px-2 py-1 text-xs font-mono truncate select-all"
                            title={shareUrl}
                            data-attr="web-analytics-share-link"
                        >
                            {shareUrl}
                        </div>
                        <LemonButton
                            type="primary"
                            size="small"
                            icon={copied ? <IconCheck /> : <IconCopy />}
                            onClick={handleCopy}
                            data-attr="web-analytics-share-copy"
                        >
                            {copied ? 'Copied' : 'Copy'}
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <LemonButton
                type="secondary"
                size="small"
                icon={emphasizeShareButton ? <IconShare /> : <IconLink />}
                tooltip={emphasizeShareButton ? undefined : 'Share'}
                tooltipPlacement="top"
                onClick={toggleOpen}
                active={isOpen}
                data-attr="web-analytics-share-button"
            >
                {emphasizeShareButton ? 'Share' : undefined}
            </LemonButton>
        </Popover>
    )
}
