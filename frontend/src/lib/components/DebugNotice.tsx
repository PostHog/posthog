import { useValues } from 'kea'
import { IconBranch, IconClose, IconCode } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { useEffect, useState } from 'react'

import { NavbarButton } from '~/layout/navigation-3000/components/NavbarButton'
import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'

export function DebugNotice(): JSX.Element | null {
    const [debugInfo, setDebugInfo] = useState<{ branch: string; revision: string } | undefined>()
    const [noticeHidden, setNoticeHidden] = useState(false)
    const { isNavCollapsedDesktop } = useValues(navigation3000Logic)

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

    if (isNavCollapsedDesktop) {
        return (
            <NavbarButton
                identifier="debug-notice"
                icon={<IconBranch color="var(--primary)" />}
                title={
                    <div>
                        <p>DEBUG mode</p>{' '}
                        <p>
                            Branch: <b>{debugInfo.branch}</b>
                        </p>
                        <p className="mb-0">
                            Revision: <b>{debugInfo.revision}</b>
                        </p>
                    </div>
                }
                onClick={() => setNoticeHidden(true)}
            />
        )
    }
    return (
        <div
            className="border rounded-md bg-bg-3000 overflow-hidden mb-1.5 w-full font-mono"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ fontSize: 13 }} // utility classes don't have a 13px variant
        >
            <div className="p-2 border-l-4 border-primary text-primary-3000 truncate flex justify-between">
                <b>DEBUG mode</b>
                <LemonButton icon={<IconClose />} size="small" noPadding onClick={() => setNoticeHidden(true)} />
            </div>
            <div className="flex items-center gap-2 px-2 h-8 border-l-4 border-brand-red truncate" title="Branch">
                <IconBranch className="text-lg" />
                <b>{debugInfo.branch}</b>
            </div>
            <div className="flex items-center gap-2 px-2 h-8 border-l-4 border-brand-yellow truncate" title="Revision">
                <IconCode className="text-lg" />
                <b>{debugInfo.revision}</b>
            </div>
        </div>
    )
}
