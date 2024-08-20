import { IconCode, IconX } from '@posthog/icons'
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
                icon={<IconBranch className="text-primary" />}
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
        <div className="border rounded bg-bg-3000 overflow-hidden mb-1.5 w-full font-mono max-w-60 text-[13px]">
            <div className="flex items-center gap-2 px-2 h-8 border-l-4 border-brand-blue justify-between">
                <b>DEBUG mode</b>
                <LemonButton
                    icon={<IconX />}
                    tooltip="Dismiss"
                    size="small"
                    noPadding
                    onClick={() => setNoticeHidden(true)}
                />
            </div>
            <div
                className="flex items-center gap-2 px-2 h-8 border-l-4 border-brand-red"
                title={`Branch: ${debugInfo.branch}`}
            >
                <IconBranch className="text-lg" />
                <b className="min-w-0 flex-1 truncate">{debugInfo.branch}</b>
            </div>
            <div
                className="flex items-center gap-2 px-2 h-8 border-l-4 border-brand-yellow"
                title={`Revision: ${debugInfo.revision}`}
            >
                <IconCode className="text-lg" />
                <b className="min-w-0 flex-1 truncate">{debugInfo.revision}</b>
            </div>
        </div>
    )
}
