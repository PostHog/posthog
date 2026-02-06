import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconCloud } from '@posthog/icons'
import { LemonBadgeProps, LemonButton, Tooltip } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { IconWithBadge } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'

import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'
import { sidePanelLogic } from '../sidePanelLogic'
import { SidePanelDocsSkeleton } from './SidePanelDocs'
import { INCIDENT_IO_STATUS_PAGE_BASE, sidePanelStatusIncidentIoLogic } from './sidePanelStatusIncidentIoLogic'
import { STATUS_PAGE_BASE, sidePanelStatusLogic } from './sidePanelStatusLogic'

export const SidePanelStatusIcon = (props: { className?: string; size?: LemonBadgeProps['size'] }): JSX.Element => {
    const { featureFlags } = useValues(featureFlagLogic)
    const useIncidentIo = !!featureFlags[FEATURE_FLAGS.INCIDENT_IO_STATUS_PAGE]

    const { status: atlassianStatus, statusPage } = useValues(sidePanelStatusLogic)
    const { status: incidentIoStatus, statusDescription: incidentIoDescription } =
        useValues(sidePanelStatusIncidentIoLogic)

    const status = useIncidentIo ? incidentIoStatus : atlassianStatus
    const title = useIncidentIo
        ? incidentIoDescription
        : statusPage?.status.description
          ? capitalizeFirstLetter(statusPage.status.description.toLowerCase())
          : null

    return (
        <Tooltip title={title} placement="left">
            <span {...props}>
                <IconWithBadge
                    content={status !== 'operational' ? '!' : '✓'}
                    size={props.size}
                    status={
                        status.includes('outage')
                            ? 'danger'
                            : status.includes('degraded') || status.includes('monitoring')
                              ? 'warning'
                              : 'success'
                    }
                    className={props.className}
                >
                    <IconCloud />
                </IconWithBadge>
            </span>
        </Tooltip>
    )
}

export const SidePanelStatus = (): JSX.Element => {
    const { closeSidePanel } = useActions(sidePanelLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const useIncidentIo = !!featureFlags[FEATURE_FLAGS.INCIDENT_IO_STATUS_PAGE]
    const [ready, setReady] = useState(false)

    useEffect(() => {
        if (useIncidentIo) {
            // For incident.io, we just redirect to the external status page
            window.open(INCIDENT_IO_STATUS_PAGE_BASE, '_blank')?.focus()
            closeSidePanel()
        }
    }, [useIncidentIo, closeSidePanel])

    if (useIncidentIo) {
        return <></>
    }

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
                    sandbox="allow-scripts allow-same-origin"
                />

                {!ready && <SidePanelDocsSkeleton />}
            </div>
        </>
    )
}
