import { useActions, useValues } from 'kea'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { billingLogic } from 'scenes/billing/billingLogic'

export function BillingUpgradeCTA({ children, disabledReason, ...props }: LemonButtonProps): JSX.Element {
    const { reportBillingCTAShown } = useActions(eventUsageLogic)
    const { billingManagedByPartnerDisabledReason } = useValues(billingLogic)
    useOnMountEffect(reportBillingCTAShown)

    return (
        <LemonButton {...props} disabledReason={billingManagedByPartnerDisabledReason || disabledReason}>
            {children}
        </LemonButton>
    )
}
