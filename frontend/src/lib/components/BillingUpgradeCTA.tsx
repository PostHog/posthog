import { useActions } from 'kea'
import type { JSX } from 'react'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

export function BillingUpgradeCTA({ children, ...props }: LemonButtonProps): JSX.Element {
    const { reportBillingCTAShown } = useActions(eventUsageLogic)
    useOnMountEffect(reportBillingCTAShown)

    return <LemonButton {...props}>{children}</LemonButton>
}
