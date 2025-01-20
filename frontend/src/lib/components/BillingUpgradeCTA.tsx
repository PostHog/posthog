import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { useEffect } from 'react'

export function BillingUpgradeCTA({ children, ...props }: LemonButtonProps): JSX.Element {
    const { reportBillingCTAShown } = useActions(eventUsageLogic)
    useEffect(() => {
        reportBillingCTAShown()
    }, [])

    return <LemonButton {...props}>{children}</LemonButton>
}
