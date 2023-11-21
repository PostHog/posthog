import { useEffect, useState } from 'react'
import { IconClose } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

export function DebugNotice(): JSX.Element | null {
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

    return (
        <div className="bg-bg-light cursor-pointer border-t" onClick={() => setNoticeHidden(true)}>
            <div className="p-2 border-l-4 border-primary text-primary-3000 truncate flex justify-between">
                <b>DEBUG mode</b>
                <LemonButton
                    status="primary-alt"
                    icon={<IconClose />}
                    size="small"
                    noPadding
                    onClick={() => setNoticeHidden(true)}
                />
            </div>
            <div className="p-2 border-l-4 border-danger text-danger-dark truncate">
                Branch: <b>{debugInfo.branch}</b>
            </div>
            <div className="p-2 border-l-4 border-warning text-warning-dark truncate">
                Revision: <b>{debugInfo.revision}</b>
            </div>
        </div>
    )
}
