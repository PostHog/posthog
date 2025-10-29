import { useActions, useValues } from 'kea'

import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

export function ActivityLogSettings(): JSX.Element {
    const { userLoading } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { reportActivityLogSettingToggled } = useActions(eventUsageLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const handleToggle = (checked: boolean): void => {
        updateCurrentTeam({ receive_org_level_activity_logs: checked })
        reportActivityLogSettingToggled(checked)
    }

    return (
        <PayGateMini feature={AvailableFeature.AUDIT_LOGS}>
            <div className="deprecated-space-y-4">
                <p>
                    <LemonButton to={urls.advancedActivityLogs()} type="primary">
                        Browse all activity logs
                    </LemonButton>
                </p>
            </div>

            {featureFlags[FEATURE_FLAGS.CDP_ACTIVITY_LOG_NOTIFICATIONS] && (
                <>
                    <div className="mt-4">
                        <h3>Organization-level activity logs</h3>
                        <p>
                            Enable organization-level activity log notifications for this environment. When enabled,
                            activity logs from organization-level changes (such as organization settings, domains, and
                            members) will also be sent to this environment, allowing you to create destinations and
                            subscriptions for these events.
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

                    <div className="mt-4">
                        <h3>Activity log notifications</h3>
                        <p>
                            Create destinations to get notified of activity logs. You can filter by activity type,
                            resource, and other properties to receive only the notifications you need.
                        </p>

                        <LinkedHogFunctions type="internal_destination" subTemplateIds={['activity-log']} />
                    </div>
                </>
            )}
        </PayGateMini>
    )
}
