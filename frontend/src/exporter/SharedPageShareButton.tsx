import { useEffect, useState } from 'react'

import { IconCheck, IconCopy, IconGlobe, IconLock, IconShare } from '@posthog/icons'

import api from 'lib/api'
import { CLICK_OUTSIDE_BLOCK_CLASS } from 'lib/hooks/useOutsideClickHandler'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { writeToClipboard } from 'lib/utils/writeToClipboard'

type CopyState = 'idle' | 'copied' | 'failed'

const COPY_LABEL: Record<CopyState, string> = { idle: 'Copy link', copied: 'Copied', failed: "Couldn't copy" }

/**
 * "Share" on a public page: the link, who it works for, and the switch that turns the link on or off
 * for viewers allowed to. The shared page mounts no toast container, so the buttons report on themselves.
 */
export function SharedPageShareButton({
    noun,
    sharingEnabled = true,
    sharingApiPath,
    open,
    onOpenChange,
}: {
    noun: 'canvas' | 'file'
    /** False while the link is off, which only viewers who can open the original ever see. */
    sharingEnabled?: boolean
    /** The sharing endpoint, for viewers who may turn the link on or off. */
    sharingApiPath?: string | null
    open: boolean
    onOpenChange: (open: boolean) => void
}): JSX.Element {
    const [copyState, setCopyState] = useState<CopyState>('idle')
    const [switching, setSwitching] = useState(false)
    const [switchFailed, setSwitchFailed] = useState(false)
    const shareUrl = window.location.href

    useEffect(() => {
        if (copyState === 'idle') {
            return
        }
        const timer = window.setTimeout(() => setCopyState('idle'), 2000)
        return () => window.clearTimeout(timer)
    }, [copyState])

    const copyLink = async (): Promise<void> => {
        const outcome = await writeToClipboard(shareUrl)
        setCopyState(outcome === 'copied' ? 'copied' : 'failed')
    }

    const toggleSharing = async (): Promise<void> => {
        if (!sharingApiPath) {
            return
        }
        setSwitching(true)
        setSwitchFailed(false)
        try {
            await api.update(sharingApiPath, { enabled: !sharingEnabled })
        } catch {
            setSwitching(false)
            setSwitchFailed(true)
            return
        }
        // The page is served for the link's new state, so a reload is the honest way to show it.
        window.location.reload()
    }

    const accessDescription = sharingEnabled
        ? `Anyone with the link sees the ${noun} as it was when it was shared.`
        : `Only people with access to this ${noun} can open this page.`

    return (
        <LemonDropdown
            visible={open}
            onVisibilityChange={onOpenChange}
            closeOnClickInside={false}
            placement="bottom-end"
            padded={false}
            overlay={
                <div className="flex w-96 flex-col gap-4 p-4">
                    <h3 className="m-0 text-base font-semibold">Share {noun}</h3>
                    {sharingApiPath ? (
                        <div className="flex items-center justify-between gap-3">
                            <div className="flex min-w-0 flex-col gap-0.5">
                                <span className="font-medium">Public link</span>
                                <span className="text-sm text-muted">
                                    {switchFailed ? "Couldn't update sharing. Try again." : accessDescription}
                                </span>
                            </div>
                            <LemonSwitch
                                checked={switching ? !sharingEnabled : sharingEnabled}
                                disabled={switching}
                                onChange={() => void toggleSharing()}
                                aria-label="Public link"
                                data-attr="shared-page-sharing-toggle"
                            />
                        </div>
                    ) : (
                        <div className="flex items-start gap-3">
                            {sharingEnabled ? (
                                <IconGlobe className="mt-0.5 shrink-0 text-xl text-muted" />
                            ) : (
                                <IconLock className="mt-0.5 shrink-0 text-xl text-muted" />
                            )}
                            <div className="flex min-w-0 flex-col gap-0.5">
                                <span className="font-medium">
                                    {sharingEnabled ? 'Anyone with the link can view' : 'Sharing is off'}
                                </span>
                                <span className="text-sm text-muted">{accessDescription}</span>
                            </div>
                        </div>
                    )}
                    <div className="flex items-center gap-2">
                        <div
                            className="flex h-10 min-w-0 flex-1 items-center rounded border border-primary bg-fill-input px-3 font-mono text-xs"
                            title={shareUrl}
                        >
                            <span className="truncate">{shareUrl}</span>
                        </div>
                        <LemonButton
                            type="primary"
                            icon={copyState === 'copied' ? <IconCheck /> : <IconCopy />}
                            status={copyState === 'failed' ? 'danger' : undefined}
                            onClick={() => void copyLink()}
                            data-attr="shared-page-copy-link"
                        >
                            {COPY_LABEL[copyState]}
                        </LemonButton>
                    </div>
                </div>
            }
        >
            {/* The trigger is not the popover's DOM reference, so without the opt-out its pointerdown dismisses
                the menu and the click that follows reopens it. */}
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconShare />}
                className={CLICK_OUTSIDE_BLOCK_CLASS}
                data-attr="shared-page-share"
            >
                Share
            </LemonButton>
        </LemonDropdown>
    )
}
