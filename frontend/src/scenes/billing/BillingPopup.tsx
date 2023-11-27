import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import { Billing } from './Billing'

export type BillingPopupProps = {
    title?: string
    description?: string
}

export function openBillingPopupModal({
    title = 'Unlock premium features',
    description,
}: BillingPopupProps = {}): void {
    LemonDialog.open({
        title: title,
        description: description,
        content: <Billing />,
        width: 800,
        primaryButton: {
            children: 'Maybe later...',
            type: 'secondary',
        },
    })
}
