import { useValues } from 'kea'

import { LemonButton, LemonModal, Link } from '@posthog/lemon-ui'

import { BigLeaguesHog } from 'lib/components/hedgehogs'
import { BillingAddonFeaturesList } from 'scenes/billing/BillingAddonFeaturesList'
import { BillingProductAddonActions } from 'scenes/billing/BillingProductAddonActions'
import { billingProductLogic } from 'scenes/billing/billingProductLogic'
import { urls } from 'scenes/urls'

import { BillingProductV2AddonType } from '~/types'

type AddonTrialModalProps = {
    product: BillingProductV2AddonType
    isOpen: boolean
    onClose: () => void
}

export function AddonTrialModal({ product, isOpen, onClose }: AddonTrialModalProps): JSX.Element {
    const { currentAndUpgradePlans } = useValues(billingProductLogic({ product }))

    const comparePlansUrl = `${urls.organizationBilling()}?products=${product.type}`

    const addonFeatures =
        currentAndUpgradePlans?.upgradePlan?.features ||
        currentAndUpgradePlans?.currentPlan?.features ||
        product.features?.filter((f) => f.name !== product.name)

    return (
        <LemonModal isOpen={isOpen} onClose={onClose} title={product.name} description={product.description}>
            <div className="flex flex-col">
                <div className="bg-surface-secondary rounded p-6 flex flex-col">
                    <div className="hidden sm:flex [@media(max-height:850px)]:hidden justify-center my-2">
                        <BigLeaguesHog className="h-auto w-auto max-w-full max-h-[250px]" />
                    </div>
                    <BillingAddonFeaturesList
                        addonFeatures={addonFeatures?.filter((f: any) => !f.entitlement_only) || []}
                        addonType={product.type}
                    />
                    <p className="ml-0 mb-0 mt-2">
                        {product.docs_url && (
                            <>
                                <Link to={product.docs_url}>Read the docs</Link> for more information.
                            </>
                        )}
                    </p>
                </div>
                <div className="flex justify-between mt-2 items-start">
                    <LemonButton
                        type="secondary"
                        size="medium"
                        className="mt-2 mb-2"
                        to={comparePlansUrl}
                        onClick={onClose}
                    >
                        Compare plans
                    </LemonButton>
                    <BillingProductAddonActions addon={product} buttonSize="medium" ctaTextOverride="Confirm" />
                </div>
            </div>
        </LemonModal>
    )
}
