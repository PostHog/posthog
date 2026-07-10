import { MemberSelectMultiple } from 'lib/components/MemberSelectMultiple'

import { InsightShortId } from '~/types'

import { AlertFormType } from 'products/alerts/frontend/logic/alertFormLogic'
import { AlertType } from 'products/alerts/frontend/types'
import { AlertDestinationSelector } from 'products/alerts/frontend/views/AlertDestinationSelector'
import { InlineAlertNotifications } from 'products/alerts/frontend/views/InlineAlertNotifications'

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
