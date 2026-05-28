import { AlertFormType } from 'lib/components/Alerts/alertFormLogic'
import { AlertType } from 'lib/components/Alerts/types'
import { AlertDestinationSelector } from 'lib/components/Alerts/views/AlertDestinationSelector'
import { InlineAlertNotifications } from 'lib/components/Alerts/views/InlineAlertNotifications'
import { MemberSelectMultiple } from 'lib/components/MemberSelectMultiple'

import { InsightShortId } from '~/types'

export interface AlertNotificationSectionProps {
    alertForm: AlertFormType
    alertId: AlertType['id'] | undefined
    insightShortId: InsightShortId
    inlineNotificationsEnabled: boolean
    onSetAlertFormValue: <K extends keyof AlertFormType>(key: K, value: AlertFormType[K]) => void
}

export function AlertNotificationSection({
    alertForm,
    alertId,
    insightShortId,
    inlineNotificationsEnabled,
    onSetAlertFormValue,
}: AlertNotificationSectionProps): JSX.Element {
    return (
        <div>
            <h3>Notification</h3>
            <div className="flex gap-4 items-center mt-2">
                <div>E-mail</div>
                <div className="flex-auto">
                    <MemberSelectMultiple
                        value={alertForm.subscribed_users?.map((u) => u.id) ?? []}
                        idKey="id"
                        onChange={(value) => onSetAlertFormValue('subscribed_users', value)}
                    />
                </div>
            </div>

            <h4 className="mt-4">Destinations</h4>
            <div className="mt-4">
                {inlineNotificationsEnabled ? (
                    <InlineAlertNotifications alertId={alertId} />
                ) : alertId ? (
                    <div className="flex flex-col">
                        <AlertDestinationSelector alertId={alertId} insightShortId={insightShortId} />
                    </div>
                ) : (
                    <div className="text-muted-alt">Save alert first to add destinations (e.g. Slack, Webhooks)</div>
                )}
            </div>
        </div>
    )
}
