import { useActions } from 'kea'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { useEffect } from 'react'

export function BillingUpgradeCTA({
    children,
    ...props
}: LemonButtonProps & React.RefAttributes<HTMLButtonElement>): JSX.Element {
    const { reportBillingCTAShown } = useActions(eventUsageLogic)
    useEffect(() => {
        reportBillingCTAShown()
    }, [])

    return <LemonButton {...props}>{children}</LemonButton>
}
