import { assertResolutionInvariant } from './src-image.ts'

describe('assertResolutionInvariant', () => {
    // The guarantee is that anything still legible in the stored image was large enough at the model
    // for the detector to have found it. It lives between the MODEL INPUT and the stored size, so it
    // can be broken three ways: storing too much, detecting too little, or shrinking the frame again
    // after the budgets were set. The third is the one no reviewer would catch by reading the two
    // pixel numbers, which is why DET_FACTOR is an argument rather than an assumption.
    it.each([
        ['the derived defaults', 450_000, 50_000, 1],
        ['a larger pair at the same ratio', 900_000, 100_000, 1],
        ['detection well above the floor', 2_560_000, 50_000, 1],
    ])('accepts %s', (_case, detect, store, detFactor) => {
        expect(() => assertResolutionInvariant(detect, store, detFactor)).not.toThrow()
    })

    it.each([
        ['storing everything that was detected', 2_560_000, 2_560_000, 1],
        ['a ratio just under the floor', 1_000_000, 125_000, 1],
        ['budgets that pass but a DET_FACTOR that spends the margin', 450_000, 50_000, 0.75],
    ])('rejects %s', (_case, detect, store, detFactor) => {
        expect(() => assertResolutionInvariant(detect, store, detFactor)).toThrow(/invariant violated/)
    })
})
