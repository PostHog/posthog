import { useEffect, useState } from 'react'

import { IconCode, IconWarning, IconX } from '@posthog/icons'
import { Link, Tooltip } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconBranch } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

export interface DebugNoticeProps {
    isCollapsed?: boolean
}

export function DebugNotice({ isCollapsed }: DebugNoticeProps): JSX.Element | null {
    const [debugInfo, setDebugInfo] = useState<{ branch: string; revision: string } | undefined>()
    const [noticeHidden, setNoticeHidden] = useState(false)

    useEffect(() => {
        const bottomNotice = document.getElementById('bottom-notice')
        const bottomNoticeRevision = document.getElementById('bottom-notice-revision')?.textContent
        const bottomNoticeBranch = document.getElementById('bottom-notice-branch')?.textContent

        if (bottomNotice && bottomNoticeRevision && bottomNoticeBranch) {
            setDebugInfo({
                branch: bottomNoticeBranch || 'unknown',
                revision: bottomNoticeRevision || 'unknown',
            })

            bottomNotice.remove()
        }

        return () => {}
    }, [])

    if (!debugInfo || noticeHidden) {
        return null
    }

    if (isCollapsed) {
        return (
            <ButtonPrimitive
                iconOnly
                tooltip={
                    <div className="font-mono">
                        <div>
                            <strong>DEBUG mode!</strong>
                        </div>
                        <div>
                            Branch: <b>{debugInfo.branch}</b>
                        </div>
                        <div>
                            Revision: <b>{debugInfo.revision}</b>
                        </div>
                        <div className="italic">Click to hide</div>
                    </div>
                }
                onClick={() => setNoticeHidden(true)}
            >
                <IconBranch className="text-secondary" />
            </ButtonPrimitive>
        )
    }
    return (
        <div className="bg-primary w-full overflow-hidden rounded border font-mono text-xs *:flex *:h-7 *:items-center *:gap-2 *:border-l-4 *:pl-2 *:pr-0.5">
            <div className="border-brand-blue justify-between">
                <b>DEBUG mode</b>
                <LemonButton
                    icon={<IconX />}
                    tooltip="Dismiss"
                    tooltipPlacement="right"
                    size="xsmall"
                    onClick={() => setNoticeHidden(true)}
                />
            </div>
            <Tooltip title="Branch" placement="right">
                <div className="border-brand-red w-fit max-w-full truncate">
                    <IconBranch className="text-base" />
                    <span className="min-w-0 flex-1 truncate font-bold">{debugInfo.branch}</span>
                </div>
            </Tooltip>
            <Tooltip title="Revision" placement="right">
                <div className="border-brand-yellow w-fit">
                    <IconCode className="text-base" />
                    <span className="min-w-0 flex-1 truncate font-bold">{debugInfo.revision}</span>
                </div>
            </Tooltip>
            {window.location.port !== '8010' && (
                <Tooltip
                    title={
                        <>
                            You're currently using the app over port 8000,
                            <br />
                            which only serves the web app, without capture (/e/).
                            <br />
                            Use port 8010 for full PostHog, proxied via Caddy.
                        </>
                    }
                    placement="right"
                >
                    <div className="border-brand-key flex h-8 w-fit items-center gap-2 border-l-4 px-2">
                        <IconWarning className="text-lg" />
                        <Link
                            to={window.location.href.replace(`:${window.location.port}`, ':8010')}
                            className="text-default min-w-0 flex-1 truncate font-semibold underline"
                        >
                            Click here to fix port!
                        </Link>
                    </div>
                </Tooltip>
            )}
        </div>
    )
}
