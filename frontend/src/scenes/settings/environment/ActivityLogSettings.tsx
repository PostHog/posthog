import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonSwitch, Tooltip } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

export function ActivityLogSettings(): JSX.Element {
    return (
        <PayGateMini feature={AvailableFeature.AUDIT_LOGS}>
            <div className="flex">
                <p>
                    <LemonButton to={urls.advancedActivityLogs()} type="primary">
                        Browse all activity logs
                    </LemonButton>
                </p>
            </div>
        </PayGateMini>
    )
}

export function ActivityLogOrgLevelSettings(): JSX.Element {
    const { userLoading } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { reportActivityLogSettingToggled } = useActions(eventUsageLogic)

    const handleToggle = (checked: boolean): void => {
        updateCurrentTeam({ receive_org_level_activity_logs: checked })
        reportActivityLogSettingToggled(checked)
    }

    return (
        <PayGateMini feature={AvailableFeature.AUDIT_LOGS}>
            <div>
                <p className="flex items-center gap-1">
                    Enable organization-level activity logs notifications for this project.
                    <Tooltip
                        title={
                            <>
                                When enabled, activity logs from organization-level changes (such as organization
                                settings, domains, and members) will also be sent to this project, allowing you to view
                                them in the activity logs page and create notifications for these events.
                            </>
                        }
                    >
                        <IconInfo className="text-lg" />
                    </Tooltip>
                </p>

                <LemonSwitch
                    id="posthog-activity-log-org-level-switch"
                    onChange={handleToggle}
                    checked={!!currentTeam?.receive_org_level_activity_logs}
                    disabled={userLoading}
                    label="Receive organization-level activity logs"
                    bordered
                />
            </div>
        </PayGateMini>
    )
}

export function ActivityLogNotifications(): JSX.Element {
    return (
        <PayGateMini feature={AvailableFeature.AUDIT_LOGS}>
            <div>
                <p className="flex items-center gap-1">
                    Create notifications to get notified of activity logs.
                    <Tooltip
                        title={
                            <>
                                You can filter by activity type, resource, and other properties to receive only the
                                notifications you need.
                            </>
                        }
                    >
                        <IconInfo className="text-lg" />
                    </Tooltip>
                </p>

                <LinkedHogFunctions type="internal_destination" subTemplateIds={['activity-log']} />
            </div>
        </PayGateMini>
    )
}
