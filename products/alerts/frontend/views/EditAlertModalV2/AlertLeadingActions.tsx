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
}

export function AlertLeadingActions({
    alertForm,
    alert,
    onDeleteAlert,
    onSnoozeAlert,
    onClearSnooze,
}: AlertLeadingActionsProps): JSX.Element {
    return (
        <div className="flex items-center gap-2">
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
            <SnoozeButton
                onChange={onSnoozeAlert}
                value={alert?.snoozed_until}
                disabledReason={alert?.state === AlertState.FIRING ? undefined : 'Only firing alerts can be snoozed'}
            />
            {alert?.state === AlertState.SNOOZED ? (
                <LemonButton
                    type="secondary"
                    status="default"
                    onClick={onClearSnooze}
                    tooltip={`Currently snoozed until ${formatDate(dayjs(alert.snoozed_until), 'MMM D, HH:mm')}`}
                >
                    Clear snooze
                </LemonButton>
            ) : null}
            <div className="ml-auto">
                <LemonField name="enabled" className="m-0">
                    <LemonSwitch checked={alertForm.enabled} data-attr="alertForm-enabled" label="Enabled" />
                </LemonField>
            </div>
        </div>
    )
}
