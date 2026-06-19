import { ProductKey } from '~/queries/schema/schema-general'

import { findArchetype } from './archetypes'
import { findRole } from './roles'

/**
 * Recommend products from the chosen company archetype, plus the selected role's add-on product.
 * Returns an empty list when no archetype is chosen. Product display metadata (name, icon, color)
 * is resolved separately from `availableOnboardingProducts` in `../../shared/utils`.
 */
export function recommendProducts(archetypeId: string | null, roleId: string | null): ProductKey[] {
    const archetype = findArchetype(archetypeId)
    if (!archetype) {
        return []
    }
    const products = [...archetype.recommendedProducts]
    const role = findRole(roleId)
    if (role?.addsProduct && !products.includes(role.addsProduct)) {
        products.push(role.addsProduct)
    }
    return products
}
