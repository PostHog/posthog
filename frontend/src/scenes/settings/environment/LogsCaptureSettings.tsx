import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { teamLogic } from 'scenes/teamLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

export function LogsCaptureSettings(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)

    return (
        <div>
            <h3>Browser console logs capture</h3>
            <p>
                Automatically capture browser session logs from your application and send them to the Logs product for
                analysis and debugging.
            </p>
            <p>
                This is separate from session replay console log capture and specifically sends logs to PostHog's
                dedicated Logs product.
            </p>
            <AccessControlAction
                resourceType={AccessControlResourceType.Logs}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <LemonSwitch
                    data-attr="opt-in-logs-capture-console-log-switch"
                    onChange={(checked) => {
                        updateCurrentTeam({
                            logs_settings: { ...currentTeam?.logs_settings, capture_console_logs: checked },
                        })
                    }}
                    label="Capture console logs to Logs product"
                    bordered
                    checked={!!currentTeam?.logs_settings?.capture_console_logs}
                    loading={currentTeamLoading}
                />
            </AccessControlAction>
        </div>
    )
}
