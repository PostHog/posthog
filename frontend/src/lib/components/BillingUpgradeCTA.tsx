import { useActions } from 'kea'
import { useEffect } from 'react'

import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

export function BillingUpgradeCTA({ children, ...props }: LemonButtonProps): JSX.Element {
    const { reportBillingCTAShown } = useActions(eventUsageLogic)
    useEffect(() => {
        reportBillingCTAShown()
    }, [reportBillingCTAShown])

    return <LemonButton {...props}>{children}</LemonButton>
}
