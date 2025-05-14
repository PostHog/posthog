import { IconStethoscope } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { IconWithBadge } from 'lib/lemon-ui/icons'
import React from 'react'

import { sidePanelSdkDoctorLogic } from './sidePanelSdkDoctorLogic'

export const SidePanelSdkDoctorIcon = (props: { className?: string }): JSX.Element => {
    const { sdkHealth } = useValues(sidePanelSdkDoctorLogic)

    const title =
        sdkHealth === 'warning'
            ? 'SDK issues detected'
            : sdkHealth === 'critical'
            ? 'Critical SDK issues detected'
            : 'SDK health is good'

    return (
        <Tooltip title={title} placement="left">
            <span {...props}>
                <IconWithBadge
                    content={sdkHealth !== 'healthy' ? '!' : '✓'}
                    status={sdkHealth === 'critical' ? 'danger' : sdkHealth === 'warning' ? 'warning' : 'success'}
                >
                    <IconStethoscope />
                </IconWithBadge>
            </span>
        </Tooltip>
    )
}

export function SidePanelSdkDoctor(): JSX.Element {
    return (
        <div className="p-4">
            <h3 className="text-lg font-semibold mb-2">SDK Doctor</h3>
            <p>SDK health check panel. This is a placeholder component that will show SDK health information.</p>
        </div>
    )
}
