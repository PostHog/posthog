import { useActions, useValues } from 'kea'

import { IconBell } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { MemberSelectMultiple } from 'lib/components/MemberSelectMultiple'

import { InsightShortId } from '~/types'

import { AlertEditorSection } from 'products/alerts/frontend/components/AlertEditor'
import { AlertFormType } from 'products/alerts/frontend/logic/alertFormLogic'
import { alertNotificationLogic } from 'products/alerts/frontend/logic/alertNotificationLogic'
import { AlertType } from 'products/alerts/frontend/types'
import { AlertDestinationSelector } from 'products/alerts/frontend/views/AlertDestinationSelector'
import { InlineAlertNotifications } from 'products/alerts/frontend/views/InlineAlertNotifications'

export interface InsightAlertNotificationSectionProps {
    alertForm: AlertFormType
    alertId: AlertType['id'] | undefined
    insightShortId: InsightShortId
    inlineNotificationsEnabled: boolean
    showSectionTitle?: boolean
    onSetAlertFormValue: <K extends keyof AlertFormType>(key: K, value: AlertFormType[K]) => void
}

export function InsightAlertNotificationSection({
    alertForm,
    alertId,
    insightShortId,
    inlineNotificationsEnabled,
    showSectionTitle = true,
    onSetAlertFormValue,
}: InsightAlertNotificationSectionProps): JSX.Element {
    const notificationLogic = alertNotificationLogic({ alertId })
    const { testDeliveryResultLoading } = useValues(notificationLogic)
    const { sendTestDelivery } = useActions(notificationLogic)

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

    const content = (
        <>
            {alertId ? (
                <div className="flex justify-end mb-4">
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={sendTestDelivery}
                        loading={testDeliveryResultLoading}
                    >
                        Send test
                    </LemonButton>
                </div>
            ) : null}
            <div className="flex gap-4 items-center">
                <div>E-mail</div>
                <div className="flex-auto" data-prevent-wizard-submit>
                    <MemberSelectMultiple
                        value={alertForm.subscribed_users?.map((user) => user.id) ?? []}
                        idKey="id"
                        onChange={(value) => onSetAlertFormValue('subscribed_users', value)}
                    />
                </div>
            </div>

            <h4 className="mt-4">Destinations</h4>
            <div className="mt-4">{destinations}</div>
        </>
    )

    if (!showSectionTitle) {
        return content
    }

    return (
        <AlertEditorSection title="Notification" icon={<IconBell className="size-4" />}>
            {content}
        </AlertEditorSection>
    )
}
