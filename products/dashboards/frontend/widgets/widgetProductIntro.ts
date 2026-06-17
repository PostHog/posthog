import type { ProductKey } from '~/queries/schema/schema-general'
import type { TeamType } from '~/types'

/**
 * A product is "available" to a team once they've completed its onboarding or shown intent for it.
 * Until then we surface its widgets as new in the Add widget picker. When the team isn't loaded yet we
 * treat the product as adopted so we don't flash a "new" nudge before we know the real state.
 */
export function teamHasAdoptedProduct(team: TeamType | null, productKey: ProductKey): boolean {
    if (!team) {
        return true
    }
    if (team.has_completed_onboarding_for?.[productKey]) {
        return true
    }
    return team.product_intents?.some((intent) => intent.product_type === productKey) ?? false
}
