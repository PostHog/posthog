import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCloud } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { IconWithBadge } from 'lib/lemon-ui/icons'
import { capitalizeFirstLetter } from 'lib/utils'

import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'
import { sidePanelLogic } from '../sidePanelLogic'
import { SidePanelDocsSkeleton } from './SidePanelDocs'
import { STATUS_PAGE_BASE, sidePanelStatusLogic } from './sidePanelStatusLogic'

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
                    status={
                        status.includes('outage')
                            ? 'danger'
                            : status.includes('degraded') || status.includes('monitoring')
                              ? 'warning'
                              : 'success'
                    }
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
