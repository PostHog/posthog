import { BillingProductV2Type } from '~/types'

export const isCompanionProduct = (product: BillingProductV2Type): boolean => !!product.companion_of

// After the parent leaves a priced plan, billing keeps the companion on its plan with `subscribed: false`,
// and it still bills.
export const isCompanionHeld = (product: BillingProductV2Type): boolean =>
    !!product.subscribed || !!product.plans?.some((plan) => plan.current_plan)

export const getHeldCompanions = (
    products: BillingProductV2Type[] | null | undefined,
    parentType: string
): BillingProductV2Type[] =>
    products?.filter((product) => product.companion_of === parentType && isCompanionHeld(product)) ?? []
