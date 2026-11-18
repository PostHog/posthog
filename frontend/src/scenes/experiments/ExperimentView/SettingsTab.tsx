import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'

import {
    EXPERIMENT_NOTIFICATION_SUB_TEMPLATES,
    NOTIFICATIONS_DESCRIPTION,
    NOTIFICATIONS_TITLE,
    useExperimentNotificationsConfig,
} from './experimentNotificationsModel'
import { QuillExperimentNotifications } from './QuillExperimentNotifications'

export function SettingsTab(): JSX.Element {
    const { shouldShow, forceFilterGroups, returnTo } = useExperimentNotificationsConfig()
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const resultsRedesign = useFeatureFlag('EXPERIMENTS_RESULTS_REDESIGN')

    if (todayRailNav && resultsRedesign) {
        return (
            <div className="flex flex-col gap-8">
                {shouldShow && (
                    <QuillExperimentNotifications forceFilterGroups={forceFilterGroups} returnTo={returnTo} />
                )}
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-8">
            {shouldShow && (
                <div>
                    <h2 className="font-semibold text-lg">{NOTIFICATIONS_TITLE}</h2>
                    <p className="text-muted text-xs mt-1">{NOTIFICATIONS_DESCRIPTION}</p>
                    <LinkedHogFunctions
                        type="internal_destination"
                        subTemplateIds={EXPERIMENT_NOTIFICATION_SUB_TEMPLATES}
                        forceFilterGroups={forceFilterGroups}
                        queryParams={{ returnTo }}
                    />
                </div>
            )}
        </div>
    )
}
