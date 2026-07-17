import { MemberSelectMultiple } from 'lib/components/MemberSelectMultiple'

import { InsightShortId } from '~/types'

import { AlertEditorSection } from 'products/alerts/frontend/components/AlertEditor'
import { AlertFormType } from 'products/alerts/frontend/logic/alertFormLogic'
import { AlertType } from 'products/alerts/frontend/types'
import { AlertDestinationSelector } from 'products/alerts/frontend/views/AlertDestinationSelector'
import { InlineAlertNotifications } from 'products/alerts/frontend/views/InlineAlertNotifications'

export interface InsightAlertNotificationSectionProps {
    alertForm: AlertFormType
    alertId: AlertType['id'] | undefined
    insightShortId: InsightShortId
    inlineNotificationsEnabled: boolean
    onSetAlertFormValue: <K extends keyof AlertFormType>(key: K, value: AlertFormType[K]) => void
}

export function InsightAlertNotificationSection({
    alertForm,
    alertId,
    insightShortId,
    inlineNotificationsEnabled,
    onSetAlertFormValue,
}: InsightAlertNotificationSectionProps): JSX.Element {
    let destinations: JSX.Element
    if (inlineNotificationsEnabled) {
        destinations = <InlineAlertNotifications alertId={alertId} />
    } else if (alertId) {
        destinations = (
            <div className="flex flex-col">
                <AlertDestinationSelector alertId={alertId} insightShortId={insightShortId} />
            </div>
        )
    } else {
        destinations = <div className="text-muted-alt">Save alert first to add destinations (e.g. Slack, Webhooks)</div>
    }

    return (
        <AlertEditorSection title="Notification">
            <div className="flex gap-4 items-center">
                <div>E-mail</div>
                <div className="flex-auto">
                    <MemberSelectMultiple
                        value={alertForm.subscribed_users?.map((user) => user.id) ?? []}
                        idKey="id"
                        onChange={(value) => onSetAlertFormValue('subscribed_users', value)}
                    />
                </div>
            </div>

            <h4 className="mt-4">Destinations</h4>
            <div className="mt-4">{destinations}</div>
        </AlertEditorSection>
    )
}
