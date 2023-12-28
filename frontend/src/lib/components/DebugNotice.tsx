import { useValues } from 'kea'
import { IconBranch, IconClose } from 'lib/lemon-ui/icons'
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
            className="cursor-pointer border rounded bg-bg-3000 overflow-hidden w-full"
            onClick={() => setNoticeHidden(true)}
        >
            <div className="p-2 border-l-4 border-primary text-primary-3000 truncate flex justify-between">
                <b>DEBUG mode</b>
                <LemonButton icon={<IconClose />} size="small" noPadding onClick={() => setNoticeHidden(true)} />
            </div>
            <div className="p-2 border-l-4 border-primary text-primary-3000 truncate">
                Branch: <b>{debugInfo.branch}</b>
            </div>
            <div className="p-2 border-l-4 border-primary text-primary-3000 truncate">
                Revision: <b>{debugInfo.revision}</b>
            </div>
        </div>
    )
}
