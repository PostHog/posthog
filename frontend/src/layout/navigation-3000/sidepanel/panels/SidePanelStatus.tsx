import { IconCloud, IconExternal } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { IconWithBadge } from 'lib/lemon-ui/icons'
import { capitalizeFirstLetter } from 'lib/utils'
import { useState } from 'react'

import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'
import { sidePanelLogic } from '../sidePanelLogic'
import { SidePanelDocsSkeleton } from './SidePanelDocs'
import { sidePanelStatusLogic, STATUS_PAGE_BASE } from './sidePanelStatusLogic'

export const SidePanelStatusIcon = (props: { className?: string }): JSX.Element => {
    const { status, statusPage } = useValues(sidePanelStatusLogic)

    /** Statuspage's hardcoded messages, e.g. "All Systems Operational". We convert this from title to sentence case. */
    const title = statusPage?.status.description
        ? capitalizeFirstLetter(statusPage.status.description.toLowerCase())
        : null

    return (
        <Tooltip title={title} placement="left">
            <span {...props}>
                <IconWithBadge
                    content={status !== 'operational' ? '!' : '✓'}
                    status={status.includes('outage') ? 'danger' : status.includes('degraded') ? 'warning' : 'success'}
                >
                    <IconCloud />
                </IconWithBadge>
            </span>
        </Tooltip>
    )
}

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
