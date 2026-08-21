import { cleanup, render, screen } from '@testing-library/react'

import { AlertState } from '~/queries/schema/schema-general'

import type { AlertFormType } from 'products/alerts/frontend/logic/alertFormLogic'
import type { AlertType } from 'products/alerts/frontend/types'

import { AlertLeadingActions } from './AlertLeadingActions'

const alert = {
    id: 'alert-1',
    state: AlertState.NOT_FIRING,
} as AlertType

const alertForm = { name: 'Checkout conversion dropped' } as AlertFormType

describe('AlertLeadingActions', () => {
    beforeEach(cleanup)

    it.each([
        ['loaded', alert, true],
        ['missing', null, false],
    ])('shows the delete action only when the alert is %s', (_, loadedAlert, showsDeleteAction) => {
        render(
            <AlertLeadingActions
                alertForm={alertForm}
                alert={loadedAlert}
                onDeleteAlert={() => {}}
                onSnoozeAlert={() => {}}
                onClearSnooze={() => {}}
                clearSnoozeLoading={false}
                onSendTestDelivery={() => {}}
                testDeliveryLoading={false}
                showTestDelivery={false}
            />
        )

        const deleteAction = screen.queryByText('Delete alert')
        if (showsDeleteAction) {
            expect(deleteAction).not.toBeNull()
            return
        }
        expect(deleteAction).toBeNull()
    })

    it('shows the snoozed state and unsnooze action instead of the snooze control', () => {
        const snoozedAlert = {
            ...alert,
            state: AlertState.SNOOZED,
            snoozed_until: '2026-08-21T14:30:00Z',
        } as AlertType

        render(
            <AlertLeadingActions
                alertForm={alertForm}
                alert={snoozedAlert}
                onDeleteAlert={() => {}}
                onSnoozeAlert={() => {}}
                onClearSnooze={() => {}}
                clearSnoozeLoading={false}
                onSendTestDelivery={() => {}}
                testDeliveryLoading={false}
                showTestDelivery={false}
            />
        )

        expect(screen.getByText(/Snoozed until/)).not.toBeNull()
        expect(screen.getByLabelText('Unsnooze alert')).not.toBeNull()
        expect(screen.queryByText('Snooze until')).toBeNull()
        expect(screen.queryByText('Clear snooze')).toBeNull()
    })
})
