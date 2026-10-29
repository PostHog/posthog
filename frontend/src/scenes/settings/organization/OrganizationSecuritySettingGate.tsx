import { useValues } from 'kea'
import posthog from 'posthog-js'

import { PayGateButton } from 'lib/components/PayGateMini/PayGateButton'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { payGateMiniLogic } from 'lib/components/PayGateMini/payGateMiniLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'

import { AvailableFeature } from '~/types'

const FEATURE = AvailableFeature.ORGANIZATION_SECURITY_SETTINGS

// The organization security setting shows the full upgrade card for this section.
// Other settings in the section show one short line, so the card does not repeat.
export function OrganizationSecuritySettingGate({
    featureDetail,
    children,
}: {
    featureDetail: string
    children: React.ReactNode
}): JSX.Element | null {
    const { isGated, productWithFeature, gateVariant, ctaLabel } = useValues(payGateMiniLogic({ feature: FEATURE }))
    const { preflight } = useValues(preflightLogic)

    if (!isGated) {
        return (
            <PayGateMini feature={FEATURE} featureDetail={featureDetail}>
                {children}
            </PayGateMini>
        )
    }

    if (preflight?.instance_preferences?.disable_paid_fs) {
        return null
    }

    return (
        <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-secondary">Upgrade your plan to use this setting.</span>
            <PayGateButton
                feature={FEATURE}
                type="secondary"
                size="small"
                onClick={() =>
                    posthog.capture('pay gate CTA clicked', {
                        product_key: productWithFeature?.type,
                        feature: FEATURE,
                        feature_detail: featureDetail,
                        gate_variant: gateVariant,
                        cta_label: ctaLabel,
                    })
                }
            />
        </div>
    )
}
