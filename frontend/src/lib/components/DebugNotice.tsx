import { IconCode, IconWarning, IconX } from '@posthog/icons'
import { Link, Tooltip } from '@posthog/lemon-ui'
import { IconBranch } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { useEffect, useState } from 'react'

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
        <div className="border rounded bg-primary overflow-hidden w-full font-mono text-xs *:flex *:items-center *:gap-2 *:pl-2 *:pr-0.5 *:h-7 *:border-l-4">
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
                <div className="w-fit border-brand-red truncate max-w-full">
                    <IconBranch className="text-base" />
                    <span className="min-w-0 flex-1 truncate font-bold">{debugInfo.branch}</span>
                </div>
            </Tooltip>
            <Tooltip title="Revision" placement="right">
                <div className="w-fit border-brand-yellow">
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
                    <div className="flex items-center gap-2 w-fit px-2 h-8 border-l-4 border-brand-key">
                        <IconWarning className="text-lg" />
                        <Link
                            to={window.location.href.replace(`:${window.location.port}`, ':8010')}
                            className="font-semibold text-default underline min-w-0 flex-1 truncate"
                        >
                            Click here to fix port!
                        </Link>
                    </div>
                </Tooltip>
            )}
        </div>
    )
}
