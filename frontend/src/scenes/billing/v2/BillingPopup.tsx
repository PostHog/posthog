import { LemonDialog } from 'lib/components/LemonDialog'
import { BillingV2 } from './Billing'

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
        content: <BillingV2 />,
        width: 800,
        primaryButton: {
            children: 'Maybe later...',
            type: 'secondary',
        },
    })
}
