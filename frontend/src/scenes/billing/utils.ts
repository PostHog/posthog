import { FEATURE_FLAGS } from 'lib/constants'

import { BillingProductV2AddonType, BillingProductV2Type } from '~/types'

export const isAddonVisible = (
    product: BillingProductV2Type,
    addon: BillingProductV2AddonType,
    featureFlags: Record<string, any>
): boolean => {
    // Filter out inclusion-only addons if personless events are not supported
    if (addon.inclusion_only && featureFlags[FEATURE_FLAGS.PERSONLESS_EVENTS_NOT_SUPPORTED]) {
        return false
    }

    // Filter out legacy addons for platform_and_support if not subscribed
    if (product.type === 'platform_and_support' && addon.legacy_product && !addon.subscribed) {
        return false
    }

    // Filter out addons that are hidden by feature flag
    const hideAddonFlag = `billing_hide_addon_${addon.type}`
    if (featureFlags[hideAddonFlag]) {
        return false
    }

    return true
}
