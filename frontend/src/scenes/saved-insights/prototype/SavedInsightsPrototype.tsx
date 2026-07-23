/**
 * PROTOTYPE — THROWAWAY CODE. Do not ship or build on top of this.
 *
 * Question: can the insights list page (/insights) be simpler, with better filtering?
 * (Assumed "insights page" = the saved insights list, not the insight editor — the list
 * is where the filter UI lives today.)
 *
 * Three structurally different variants on the existing /insights route, switchable via
 * `?variant=` and the floating bottom bar (dev builds only):
 *   A — Filter by example: click a tag or creator in the list to filter by it; one compact
 *       "Filters" panel replaces the scattered dropdown row; active filters are removable chips.
 *   B — Faceted top bar: every filter permanently visible in labeled rows above the list.
 *   C — Quick pills + card gallery: one-click type/scope pills above a visual card grid.
 *
 * All variants read the real savedInsightsLogic, so filtering hits the live API.
 * Mutations (delete, rename, favorite) are intentionally not wired up.
 */
import { PrototypeVariantOption } from 'lib/components/PrototypeVariantSwitcher'

import { CardGalleryVariant } from './CardGalleryVariant'
import { FacetTopBarVariant } from './FacetTopBarVariant'
import { FilterByExampleVariant } from './FilterByExampleVariant'

export const SAVED_INSIGHTS_PROTOTYPE_ID = 'saved-insights-filtering'

export const SAVED_INSIGHTS_PROTOTYPE_VARIANTS: PrototypeVariantOption[] = [
    { key: 'A', name: 'Filter by example' },
    { key: 'B', name: 'Faceted top bar' },
    { key: 'C', name: 'Pills + card gallery' },
]

export function SavedInsightsPrototype({ variant }: { variant: string }): JSX.Element | null {
    switch (variant) {
        case 'A':
            return <FilterByExampleVariant />
        case 'B':
            return <FacetTopBarVariant />
        case 'C':
            return <CardGalleryVariant />
        default:
            return null
    }
}
