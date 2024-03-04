import { useActions } from 'kea'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { useEffect } from 'react'

export function BillingUpgradeCTA({ children, ...props }: LemonButtonProps): JSX.Element {
    const { reportBillingCTASeen } = useActions(eventUsageLogic)
    useEffect(() => {
        reportBillingCTASeen()
    }, [])

    return <LemonButton {...props}>{children}</LemonButton>
}
