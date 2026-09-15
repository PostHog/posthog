import { useEffect, useState } from 'react'

import { IconCheck, IconCopy, IconExternal, IconGlobe, IconShare } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Popover } from 'lib/lemon-ui/Popover'
import { writeToClipboard } from 'lib/utils/writeToClipboard'

type CopyState = 'idle' | 'copied' | 'failed'

/**
 * "Share" on a public page: who can open the link, a copy button, and the way into the desktop app when
 * the owner allows copies. The shared page mounts no toast container, so the copy button reports on itself.
 */
export function SharedPageShareButton({
    noun,
    forkUrl,
}: {
    noun: 'canvas' | 'file'
    /** Where a viewer gets their own copy; null when the owner has not allowed that. */
    forkUrl?: string | null
}): JSX.Element {
    const [open, setOpen] = useState(false)
    const [copyState, setCopyState] = useState<CopyState>('idle')

    useEffect(() => {
        if (copyState === 'idle') {
            return
        }
        const timer = window.setTimeout(() => setCopyState('idle'), 2000)
        return () => window.clearTimeout(timer)
    }, [copyState])

    const copyLink = async (): Promise<void> => {
        const outcome = await writeToClipboard(window.location.href)
        setCopyState(outcome === 'copied' ? 'copied' : 'failed')
    }

    return (
        <Popover
            visible={open}
            onClickOutside={() => setOpen(false)}
            placement="bottom-end"
            overlay={
                <div className="flex w-80 flex-col gap-3">
                    <div className="flex items-center justify-between gap-3">
                        <h3 className="m-0 text-base font-semibold">Share {noun}</h3>
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={copyState === 'copied' ? <IconCheck /> : <IconCopy />}
                            status={copyState === 'failed' ? 'danger' : undefined}
                            onClick={() => void copyLink()}
                            data-attr="shared-page-copy-link"
                        >
                            {copyState === 'copied' ? 'Copied' : copyState === 'failed' ? "Couldn't copy" : 'Copy link'}
                        </LemonButton>
                    </div>
                    <div className="flex flex-col gap-1.5">
                        <span className="text-xs font-medium text-muted">General access</span>
                        <div className="flex items-center gap-3 rounded border border-primary px-3 py-2">
                            <IconGlobe className="shrink-0 text-lg text-muted" />
                            <div className="flex min-w-0 flex-col">
                                <span className="font-medium">Anyone with the link</span>
                                <span className="text-xs text-muted">
                                    Can view the {noun} as it was when it was shared.
                                </span>
                            </div>
                        </div>
                    </div>
                    {forkUrl && (
                        // The copy flow lives in the signed-in app, so this is a full page load, not a client-side route.
                        <LemonButton
                            type="secondary"
                            fullWidth
                            center
                            icon={<IconExternal />}
                            to={forkUrl}
                            disableClientSideRouting
                            data-attr="shared-page-open-copy"
                        >
                            Open a copy in PostHog Desktop
                        </LemonButton>
                    )}
                </div>
            }
        >
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconShare />}
                active={open}
                onClick={() => setOpen(!open)}
                data-attr="shared-page-share"
            >
                Share
            </LemonButton>
        </Popover>
    )
}
