import React, { useEffect, useState } from 'react'
import { IconClose } from './icons'
import { LemonButton } from './LemonButton'

export function DebugNotice(): JSX.Element {
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
        return <></>
    }

    return (
        <div className="bg-white cursor-pointer border-t" onClick={() => setNoticeHidden(true)}>
            <div className="py-1 px-2 border-l-4 border-primary text-primary-dark  truncate flex justify-between">
                <b>DEBUG mode</b>
                <LemonButton icon={<IconClose />} size="small" onClick={() => setNoticeHidden(true)} />
            </div>
            <div className="py-1 px-2 border-l-4 border-danger text-danger-dark  truncate">
                Branch: <b>{debugInfo.branch}</b>
            </div>
            <div className="py-1 px-2 border-l-4 border-warning text-warning-dark  truncate">
                Revision: <b>{debugInfo.revision}</b>
            </div>
            <div className="py-1 px-2 border-l-4 border-default font-bold">Click to hide</div>
        </div>
    )
}
