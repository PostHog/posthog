import { IconExternal } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions } from 'kea'
import { useState } from 'react'

import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'
import { sidePanelLogic } from '../sidePanelLogic'
import { SidePanelDocsSkeleton } from './SidePanelDocs'
import { STATUS_PAGE_BASE } from './sidePanelStatusLogic'

export const SidePanelStatus = (): JSX.Element => {
    const { closeSidePanel } = useActions(sidePanelLogic)
    const [ready, setReady] = useState(false)

    return (
        <>
            <SidePanelPaneHeader>
                <div className="flex-1" />
                <LemonButton
                    size="small"
                    sideIcon={<IconExternal />}
                    targetBlank
                    // We can't use the normal `to` property as that is intercepted to open this panel :D
                    onClick={() => {
                        window.open(STATUS_PAGE_BASE, '_blank')?.focus()
                        closeSidePanel()
                    }}
                >
                    Open in new tab
                </LemonButton>
            </SidePanelPaneHeader>
            <div className="relative flex-1 overflow-hidden">
                <iframe
                    src={STATUS_PAGE_BASE}
                    title="Status"
                    className={clsx('w-full h-full', !ready && 'hidden')}
                    onLoad={() => setReady(true)}
                />

                {!ready && <SidePanelDocsSkeleton />}
            </div>
        </>
    )
}
