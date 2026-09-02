/** Raw counts carried on each variant's chart series, for the tooltip and the actors query. */
export interface VariantFunnelMeta {
    variantKey: string
    /** Absolute converted count per step; index 0 is the exposure count. */
    counts: number[]
}
