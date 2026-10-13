import { IconClock, IconX } from '@posthog/icons'
import { LemonDialog } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { formatDate } from 'lib/utils/datetime'

import { AlertState } from '~/queries/schema/schema-general'

import { SnoozeButton } from 'products/alerts/frontend/components/SnoozeButton'
import { AlertFormType } from 'products/alerts/frontend/logic/alertFormLogic'
import type { AlertType } from 'products/alerts/frontend/types'

interface AlertLeadingActionsProps {
    alertForm: AlertFormType
    alert: AlertType | null
    onDeleteAlert: () => void
    onSnoozeAlert: (snoozeUntil: string) => void
    onClearSnooze: () => void
    clearSnoozeLoading: boolean
    onSendTestDelivery: () => void
    testDeliveryLoading: boolean
    testDeliveryDisabledReason?: string
    showTestDelivery: boolean
}

export function AlertLeadingActions({
    alertForm,
    alert,
    onDeleteAlert,
    onSnoozeAlert,
    onClearSnooze,
    clearSnoozeLoading,
    onSendTestDelivery,
    testDeliveryLoading,
    testDeliveryDisabledReason,
    showTestDelivery,
}: AlertLeadingActionsProps): JSX.Element {
    const isSnoozed = alert?.state === AlertState.SNOOZED

    return (
        <div className="flex flex-wrap items-center gap-2">
            {alert ? (
                <LemonButton
                    type="secondary"
                    status="danger"
                    onClick={() => {
                        LemonDialog.open({
                            title: `Delete "${alertForm.name || 'this alert'}"?`,
                            description: 'This alert will be permanently deleted. This action cannot be undone.',
                            primaryButton: {
                                children: 'Delete',
                                type: 'primary',
                                status: 'danger',
                                onClick: onDeleteAlert,
                                'data-attr': 'alert-delete-confirm',
                            },
                            secondaryButton: { children: 'Cancel' },
                        })
                    }}
                >
                    Delete alert
                </LemonButton>
            ) : null}
            {!isSnoozed ? (
                <SnoozeButton
                    onChange={onSnoozeAlert}
                    disabledReason={
                        alert?.state === AlertState.FIRING ? undefined : 'Only firing alerts can be snoozed'
                    }
                />
            ) : null}
            {showTestDelivery ? (
                <LemonButton
                    type="secondary"
                    onClick={onSendTestDelivery}
                    loading={testDeliveryLoading}
                    disabledReason={testDeliveryDisabledReason}
                >
                    Test delivery
                </LemonButton>
            ) : null}
            {isSnoozed ? (
                <div className="flex items-center gap-1.5 text-sm text-muted-alt">
                    <IconClock className="size-4" />
                    <span>
                        {alert.snoozed_until
                            ? `Snoozed until ${formatDate(dayjs(alert.snoozed_until), 'MMM D, HH:mm')}`
                            : 'Snoozed'}
                    </span>
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        icon={<IconX />}
                        onClick={onClearSnooze}
                        loading={clearSnoozeLoading}
                        tooltip="Unsnooze alert"
                        aria-label="Unsnooze alert"
                    />
                </div>
            ) : null}
        </div>
    )
}

export function AlertEnabledAction({ alertForm }: Pick<AlertLeadingActionsProps, 'alertForm'>): JSX.Element {
    return (
        <LemonField name="enabled" className="m-0">
            <LemonSwitch checked={alertForm.enabled} data-attr="alertForm-enabled" label="Enabled" />
        </LemonField>
    )
}
