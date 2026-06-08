/** The legacy TaxonomicFilter surface, derived from the category-dropdown A/B
 *  variant, stamped on the `taxonomic filter *` telemetry events so the arms are
 *  distinguishable by an explicit property rather than a feature-flag join. The
 *  rebuild menu emits `rebuild-menu` for the same purpose. */
export function legacyTaxonomicSurface(
    categoryDropdownVariant: string | boolean | undefined
): 'legacy-control' | 'legacy-pill' {
    return categoryDropdownVariant === 'pill' ? 'legacy-pill' : 'legacy-control'
}
