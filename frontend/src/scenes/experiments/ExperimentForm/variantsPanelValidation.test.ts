import type { MultivariateFlagVariant } from '~/types'

import { validateVariants } from './variantsPanelValidation'

describe('variantsPanelValidation', () => {
    describe('validateVariants', () => {
        describe('flag key validation', () => {
            it('detects missing flag key', () => {
                const result = validateVariants({
                    flagKey: null,
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'test', rollout_percentage: 50 },
                    ],
                    featureFlagKeyValidation: null,
                })

                expect(result.rules.hasFlagKey).toBe(false)
                expect(result.hasErrors).toBe(true)
            })

            it('detects empty string flag key', () => {
                const result = validateVariants({
                    flagKey: '',
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'test', rollout_percentage: 50 },
                    ],
                    featureFlagKeyValidation: null,
                })

                expect(result.rules.hasFlagKey).toBe(false)
                expect(result.hasErrors).toBe(true)
            })

            it('accepts valid flag key', () => {
                const result = validateVariants({
                    flagKey: 'test-flag',
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'test', rollout_percentage: 50 },
                    ],
                    featureFlagKeyValidation: null,
                })

                expect(result.rules.hasFlagKey).toBe(true)
            })

            it('detects flag key validation error', () => {
                const result = validateVariants({
                    flagKey: 'test-flag',
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'test', rollout_percentage: 50 },
                    ],
                    featureFlagKeyValidation: { valid: false, error: 'Key already exists' },
                })

                expect(result.rules.hasFlagKeyError).toBe(true)
                expect(result.hasErrors).toBe(true)
            })

            it('accepts valid flag key validation', () => {
                const result = validateVariants({
                    flagKey: 'test-flag',
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'test', rollout_percentage: 50 },
                    ],
                    featureFlagKeyValidation: { valid: true, error: null },
                })

                expect(result.rules.hasFlagKeyError).toBe(false)
                expect(result.hasErrors).toBe(false)
            })
        })

        describe('variant count validation', () => {
            it('detects insufficient variants (0)', () => {
                const result = validateVariants({
                    flagKey: 'test-flag',
                    variants: [],
                    featureFlagKeyValidation: null,
                })

                expect(result.rules.hasEnoughVariants).toBe(false)
                expect(result.hasErrors).toBe(true)
            })

            it('detects insufficient variants (1)', () => {
                const result = validateVariants({
                    flagKey: 'test-flag',
                    variants: [{ key: 'control', rollout_percentage: 100 }],
                    featureFlagKeyValidation: null,
                })

                expect(result.rules.hasEnoughVariants).toBe(false)
                expect(result.hasErrors).toBe(true)
            })

            it('accepts 2 variants', () => {
                const result = validateVariants({
                    flagKey: 'test-flag',
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'test', rollout_percentage: 50 },
                    ],
                    featureFlagKeyValidation: null,
                })

                expect(result.rules.hasEnoughVariants).toBe(true)
            })

            it('accepts 3+ variants', () => {
                const result = validateVariants({
                    flagKey: 'test-flag',
                    variants: [
                        { key: 'control', rollout_percentage: 33 },
                        { key: 'test-a', rollout_percentage: 33 },
                        { key: 'test-b', rollout_percentage: 34 },
                    ],
                    featureFlagKeyValidation: null,
                })

                expect(result.rules.hasEnoughVariants).toBe(true)
            })
        })

        describe('rollout percentage validation', () => {
            it('validates correct rollout (100%)', () => {
                const result = validateVariants({
                    flagKey: 'test-flag',
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'test', rollout_percentage: 50 },
                    ],
                    featureFlagKeyValidation: null,
                })

                expect(result.rules.totalRollout).toBe(100)
                expect(result.rules.isValidRollout).toBe(true)
                expect(result.hasErrors).toBe(false)
            })

            it('detects rollout sum > 100', () => {
                const result = validateVariants({
                    flagKey: 'test-flag',
                    variants: [
                        { key: 'control', rollout_percentage: 60 },
                        { key: 'test', rollout_percentage: 50 },
                    ],
                    featureFlagKeyValidation: null,
                })

                expect(result.rules.totalRollout).toBe(110)
                expect(result.rules.isValidRollout).toBe(false)
                expect(result.hasErrors).toBe(true)
            })

            it('detects rollout sum < 100', () => {
                const result = validateVariants({
                    flagKey: 'test-flag',
                    variants: [
                        { key: 'control', rollout_percentage: 40 },
                        { key: 'test', rollout_percentage: 50 },
                    ],
                    featureFlagKeyValidation: null,
                })

                expect(result.rules.totalRollout).toBe(90)
                expect(result.rules.isValidRollout).toBe(false)
                expect(result.hasErrors).toBe(true)
            })

            it('handles missing rollout_percentage (treats as 0)', () => {
                const result = validateVariants({
                    flagKey: 'test-flag',
                    variants: [{ key: 'control', rollout_percentage: 50 }, { key: 'test' } as MultivariateFlagVariant],
                    featureFlagKeyValidation: null,
                })

                expect(result.rules.totalRollout).toBe(50)
                expect(result.rules.isValidRollout).toBe(false)
            })

            it('handles negative rollout percentages', () => {
                const result = validateVariants({
                    flagKey: 'test-flag',
                    variants: [
                        { key: 'control', rollout_percentage: 150 },
                        { key: 'test', rollout_percentage: -50 },
                    ],
                    featureFlagKeyValidation: null,
                })

                expect(result.rules.totalRollout).toBe(100)
                expect(result.rules.isValidRollout).toBe(true)
            })
        })

        describe('variant key validation', () => {
            it('detects empty variant key', () => {
                const result = validateVariants({
                    flagKey: 'test-flag',
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: '', rollout_percentage: 50 },
                    ],
                    featureFlagKeyValidation: null,
                })

                expect(result.rules.areVariantKeysValid).toBe(false)
                expect(result.hasErrors).toBe(true)
            })

            it('detects whitespace-only variant key', () => {
                const result = validateVariants({
                    flagKey: 'test-flag',
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: '   ', rollout_percentage: 50 },
                    ],
                    featureFlagKeyValidation: null,
                })

                expect(result.rules.areVariantKeysValid).toBe(false)
                expect(result.hasErrors).toBe(true)
            })

            it('detects duplicate variant keys', () => {
                const result = validateVariants({
                    flagKey: 'test-flag',
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'control', rollout_percentage: 50 },
                    ],
                    featureFlagKeyValidation: null,
                })

                expect(result.rules.hasDuplicateKeys).toBe(true)
                expect(result.hasErrors).toBe(true)
            })

            it('accepts valid variant keys', () => {
                const result = validateVariants({
                    flagKey: 'test-flag',
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'test', rollout_percentage: 50 },
                    ],
                    featureFlagKeyValidation: null,
                })

                expect(result.rules.areVariantKeysValid).toBe(true)
                expect(result.rules.hasDuplicateKeys).toBe(false)
            })

            it('handles case-sensitive duplicate detection', () => {
                const result = validateVariants({
                    flagKey: 'test-flag',
                    variants: [
                        { key: 'Control', rollout_percentage: 50 },
                        { key: 'control', rollout_percentage: 50 },
                    ],
                    featureFlagKeyValidation: null,
                })

                expect(result.rules.hasDuplicateKeys).toBe(false)
            })
        })

        describe('hasErrors calculation', () => {
            it('returns true when flag key is missing', () => {
                const result = validateVariants({
                    flagKey: null,
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'test', rollout_percentage: 50 },
                    ],
                    featureFlagKeyValidation: null,
                })

                expect(result.hasErrors).toBe(true)
            })

            it('returns true when not enough variants', () => {
                const result = validateVariants({
                    flagKey: 'test-flag',
                    variants: [{ key: 'control', rollout_percentage: 100 }],
                    featureFlagKeyValidation: null,
                })

                expect(result.hasErrors).toBe(true)
            })

            it('returns true when rollout is invalid', () => {
                const result = validateVariants({
                    flagKey: 'test-flag',
                    variants: [
                        { key: 'control', rollout_percentage: 60 },
                        { key: 'test', rollout_percentage: 50 },
                    ],
                    featureFlagKeyValidation: null,
                })

                expect(result.hasErrors).toBe(true)
            })

            it('returns true when flag key has validation error', () => {
                const result = validateVariants({
                    flagKey: 'test-flag',
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'test', rollout_percentage: 50 },
                    ],
                    featureFlagKeyValidation: { valid: false, error: 'Duplicate key' },
                })

                expect(result.hasErrors).toBe(true)
            })

            it('returns true when variant keys are invalid', () => {
                const result = validateVariants({
                    flagKey: 'test-flag',
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: '', rollout_percentage: 50 },
                    ],
                    featureFlagKeyValidation: null,
                })

                expect(result.hasErrors).toBe(true)
            })

            it('returns true when variant keys are duplicated', () => {
                const result = validateVariants({
                    flagKey: 'test-flag',
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'control', rollout_percentage: 50 },
                    ],
                    featureFlagKeyValidation: null,
                })

                expect(result.hasErrors).toBe(true)
            })

            it('returns false when all validation passes', () => {
                const result = validateVariants({
                    flagKey: 'test-flag',
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'test', rollout_percentage: 50 },
                    ],
                    featureFlagKeyValidation: { valid: true, error: null },
                })

                expect(result.hasErrors).toBe(false)
            })
        })

        describe('edge cases', () => {
            it('handles null featureFlagKeyValidation', () => {
                const result = validateVariants({
                    flagKey: 'test-flag',
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'test', rollout_percentage: 50 },
                    ],
                    featureFlagKeyValidation: null,
                })

                expect(result.rules.hasFlagKeyError).toBe(false)
            })

            it('handles empty variants array', () => {
                const result = validateVariants({
                    flagKey: 'test-flag',
                    variants: [],
                    featureFlagKeyValidation: null,
                })

                expect(result.rules.totalRollout).toBe(0)
                expect(result.rules.areVariantKeysValid).toBe(true) // vacuously true
            })
        })
    })
})
