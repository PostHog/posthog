import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { paymentEntryLogic } from './paymentEntryLogic'

export const PaymentCompletion = (): JSX.Element | null => {
    const { completedPaymentOrganization } = useValues(paymentEntryLogic)
    const { viewCompletedPaymentOrganization } = useActions(paymentEntryLogic)
    if (!completedPaymentOrganization) {
        return null
    }
    return (
        <div className="flex flex-col gap-2">
            <LemonBanner type="success">Payment setup completed for {completedPaymentOrganization.name}</LemonBanner>
            <LemonButton type="primary" onClick={viewCompletedPaymentOrganization}>
                View {completedPaymentOrganization.name}’s billing
            </LemonButton>
        </div>
    )
}
