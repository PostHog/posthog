import { LemonDialog } from 'lib/components/LemonDialog'
import { BillingV2 } from './control/Billing'
import { BillingV2 as BillingV2Test } from './test/Billing'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { useValues } from 'kea'

export type BillingPopupProps = {
    title?: string
    description?: string
}

export function openBillingPopupModal({
    title = 'Unlock premium features',
    description,
}: BillingPopupProps = {}): void {
    const { featureFlags } = useValues(featureFlagLogic)

    LemonDialog.open({
        title: title,
        description: description,
        content: (
            <>
                {featureFlags[FEATURE_FLAGS.BILLING_FEATURES_EXPERIMENT] === 'test' ? <BillingV2Test /> : <BillingV2 />}
            </>
        ),
        width: 800,
        primaryButton: {
            children: 'Maybe later...',
            type: 'secondary',
        },
    })
}
