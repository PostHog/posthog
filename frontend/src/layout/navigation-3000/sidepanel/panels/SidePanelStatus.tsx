import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconCloud } from '@posthog/icons'
import { LemonBadgeProps, Tooltip } from '@posthog/lemon-ui'

import { IconWithBadge } from 'lib/lemon-ui/icons'

import { INCIDENT_IO_STATUS_PAGE_BASE } from '~/layout/navigation-3000/incident/incidentStatus'

import { sidePanelLogic } from '../sidePanelLogic'
import { sidePanelStatusIncidentIoLogic } from './sidePanelStatusIncidentIoLogic'

export const SidePanelStatusIcon = (props: { className?: string; size?: LemonBadgeProps['size'] }): JSX.Element => {
    const { status, statusDescription } = useValues(sidePanelStatusIncidentIoLogic)

    return (
        <Tooltip title={statusDescription} placement="left">
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

    useEffect(() => {
        // Redirect to the external status page
        window.open(INCIDENT_IO_STATUS_PAGE_BASE, '_blank')?.focus()
        closeSidePanel()
    }, [closeSidePanel])

    return <></>
}
