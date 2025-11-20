import { useActions, useValues } from 'kea'

import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { notificationsLogic } from 'lib/logic/notificationsLogic'

export function NotificationPreferences(): JSX.Element {
    const { preferencesLoading, preferencesByResourceType } = useValues(notificationsLogic)
    const { updatePreference } = useActions(notificationsLogic)

    const notificationTypes = [
        {
            resource_type: 'feature_flag',
            title: 'Feature flags',
            description: 'Get notified when feature flags are created, updated, or deleted',
        },
        {
            resource_type: 'insight',
            title: 'Insights',
            description: 'Get notified about changes to insights and dashboards',
        },
        {
            resource_type: 'experiment',
            title: 'Experiments',
            description: 'Get notified about experiment results and status changes',
        },
        {
            resource_type: 'alert',
            title: 'Alerts',
            description: 'Get notified when alerts are triggered',
        },
        {
            resource_type: 'data_warehouse',
            title: 'Data warehouse',
            description: 'Get notified about data warehouse sync status and errors',
        },
        {
            resource_type: 'batch_export',
            title: 'Batch exports',
            description: 'Get notified about batch export status and failures',
        },
    ]

    if (preferencesLoading) {
        return (
            <div className="flex items-center justify-center p-8">
                <Spinner />
            </div>
        )
    }

    return (
        <div className="space-y-4">
            <div>
                <h2 className="subtitle">Notification preferences</h2>
                <p className="text-muted">
                    Choose which types of notifications you want to receive. By default, all notifications are enabled.
                </p>
            </div>

            <LemonDivider />

            <div className="space-y-4">
                {notificationTypes.map((type) => {
                    const isEnabled = preferencesByResourceType[type.resource_type] !== false

                    return (
                        <div key={type.resource_type} className="flex items-start justify-between gap-4 py-2">
                            <div className="flex-1">
                                <h3 className="mb-1 text-sm font-semibold">{type.title}</h3>
                                <p className="text-xs text-muted">{type.description}</p>
                            </div>
                            <div className="flex-shrink-0">
                                <LemonSwitch
                                    checked={isEnabled}
                                    onChange={(checked) => updatePreference(type.resource_type, checked)}
                                    label={isEnabled ? 'Enabled' : 'Disabled'}
                                    bordered
                                />
                            </div>
                        </div>
                    )
                })}
            </div>

            <LemonDivider />

            <div className="text-muted-alt text-xs">
                <p>
                    Notifications are delivered in real-time to this app. You can also access your notification history
                    from the notification bell icon in the top navigation.
                </p>
            </div>
        </div>
    )
}
