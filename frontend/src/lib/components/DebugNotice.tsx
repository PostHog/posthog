import { IconCode, IconWarning, IconX } from '@posthog/icons'
import { Link, Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { IconBranch } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { useEffect, useState } from 'react'

import { NavbarButton } from '~/layout/navigation-3000/components/NavbarButton'
import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'

export function DebugNotice(): JSX.Element | null {
    const [debugInfo, setDebugInfo] = useState<{ branch: string; revision: string } | undefined>()
    const [noticeHidden, setNoticeHidden] = useState(false)
    const { isNavCollapsed } = useValues(navigation3000Logic)

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

    if (isNavCollapsed) {
        return (
            <NavbarButton
                identifier="debug-notice"
                icon={<IconBranch className="text-accent" />}
                title={
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
            />
        )
    }
    return (
        <div className="border rounded bg-primary overflow-hidden mb-1.5 w-full font-mono max-w-60 text-[13px]">
            <div className="flex items-center gap-2 px-2 h-8 border-l-4 border-brand-blue justify-between">
                <b>DEBUG mode</b>
                <LemonButton
                    icon={<IconX />}
                    tooltip="Dismiss"
                    tooltipPlacement="right"
                    size="small"
                    noPadding
                    onClick={() => setNoticeHidden(true)}
                />
            </div>
            <Tooltip title="Branch" placement="right">
                <div className="flex items-center gap-2 w-fit px-2 h-8 border-l-4 border-brand-red truncate max-w-full">
                    <IconBranch className="text-lg" />
                    <span className="min-w-0 flex-1 truncate font-bold">{debugInfo.branch}</span>
                </div>
            </Tooltip>
            <Tooltip title="Revision" placement="right">
                <div className="flex items-center gap-2 w-fit px-2 h-8 border-l-4 border-brand-yellow">
                    <IconCode className="text-lg" />
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
