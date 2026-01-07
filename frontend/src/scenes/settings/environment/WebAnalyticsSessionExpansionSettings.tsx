import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { teamLogic } from 'scenes/teamLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

export function WebAnalyticsSessionExpansionSettings(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    const savedSetting = currentTeam?.web_analytics_session_expansion_enabled ?? true
    const [sessionExpansionEnabled, setSessionExpansionEnabled] = useState<boolean>(savedSetting)

    const handleSave = (): void => {
        updateCurrentTeam({ web_analytics_session_expansion_enabled: sessionExpansionEnabled })
    }

    return (
        <>
            <p>
                When enabled, Web Analytics includes sessions that started up to 1 hour before your selected date range.
                This provides more complete session data but may show different totals than Product Analytics trends.
            </p>
            <p className="text-muted-alt text-sm">
                Disable this to use strict date boundaries, which will make Web Analytics totals more closely match
                Product Analytics trends for the same date range.
            </p>
            <AccessControlAction
                resourceType={AccessControlResourceType.WebAnalytics}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <LemonSwitch
                    checked={sessionExpansionEnabled}
                    onChange={(enabled) => setSessionExpansionEnabled(enabled)}
                    label="Include sessions starting before date range"
                />
            </AccessControlAction>
            <div className="mt-4">
                <AccessControlAction
                    resourceType={AccessControlResourceType.WebAnalytics}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <LemonButton
                        type="primary"
                        onClick={handleSave}
                        disabledReason={sessionExpansionEnabled === savedSetting ? 'No changes to save' : undefined}
                    >
                        Save
                    </LemonButton>
                </AccessControlAction>
            </div>
        </>
    )
}
