import type { MultivariateFlagVariant } from '~/types'

export type VariantValidationRules = {
    hasFlagKey: boolean
    hasFlagKeyError: boolean
    hasEnoughVariants: boolean
    totalRollout: number
    isValidRollout: boolean
    areVariantKeysValid: boolean
    hasDuplicateKeys: boolean
}

export type VariantValidationResult = {
    hasErrors: boolean
    hasWarnings: boolean
    rules: VariantValidationRules
}

export const validateVariants = ({
    flagKey,
    variants,
    featureFlagKeyValidation,
    mode,
}: {
    flagKey: string | null
    variants: MultivariateFlagVariant[]
    featureFlagKeyValidation: { valid: boolean; error: string | null } | null
    mode?: 'create' | 'link'
}): VariantValidationResult => {
    const hasFlagKey = !!flagKey
    // In 'link' mode, we're using an existing flag, so don't validate key availability
    const hasFlagKeyError = mode === 'link' ? false : featureFlagKeyValidation?.valid === false
    const hasEnoughVariants = variants.length >= 2
    const totalRollout = variants.reduce((sum, v) => sum + (v.rollout_percentage || 0), 0)
    const isValidRollout = totalRollout === 100

    // Variant key validation
    const areVariantKeysValid = variants.every(({ key }) => key && key.trim().length > 0)
    const variantKeys = variants.map(({ key }) => key)
    const hasDuplicateKeys = variantKeys.length !== new Set(variantKeys).size

    const hasErrors =
        !hasFlagKey ||
        !hasEnoughVariants ||
        !isValidRollout ||
        hasFlagKeyError ||
        !areVariantKeysValid ||
        hasDuplicateKeys

    const hasWarnings =
        hasFlagKey &&
        hasEnoughVariants &&
        hasDuplicateKeys &&
        !isValidRollout &&
        !hasFlagKeyError &&
        !areVariantKeysValid

    return {
        hasErrors,
        hasWarnings,
        rules: {
            hasFlagKey,
            hasFlagKeyError,
            hasEnoughVariants,
            totalRollout,
            isValidRollout,
            areVariantKeysValid,
            hasDuplicateKeys,
        },
    }
}

export const getVariantValidationErrors = ({
    flagKey,
    variants,
    featureFlagKeyValidation,
    mode,
}: {
    flagKey: string | null
    variants: MultivariateFlagVariant[]
    featureFlagKeyValidation: { valid: boolean; error: string | null } | null
    mode?: 'create' | 'link'
}): string[] => {
    const errors: string[] = []
    const variantsValidation = validateVariants({ flagKey, variants, featureFlagKeyValidation, mode })

    if (!variantsValidation.rules.hasFlagKey) {
        errors.push('Feature flag key is required')
    }

    if (variantsValidation.rules.hasFlagKeyError && featureFlagKeyValidation?.error) {
        errors.push(featureFlagKeyValidation.error)
    }

    if (!variantsValidation.rules.hasEnoughVariants) {
        errors.push('At least 2 variants are required')
    }

    if (!variantsValidation.rules.areVariantKeysValid) {
        errors.push('All variants must have a key')
    }

    if (variantsValidation.rules.hasDuplicateKeys) {
        errors.push('Variant keys must be unique')
    }

    if (!variantsValidation.rules.isValidRollout) {
        errors.push(`Variant rollout must total 100% (currently ${variantsValidation.rules.totalRollout}%)`)
    }

    return errors
}

export const buildVariantSummary = (variants: MultivariateFlagVariant[], result: VariantValidationResult): string => {
    const { rules } = result
    const { areVariantKeysValid, hasDuplicateKeys, isValidRollout, totalRollout } = rules

    const count = variants.length
    if (count === 0) {
        return 'No variants configured'
    } // should never happen
    if (count === 1) {
        return '1 variant (need at least 2)'
    } // should never happen

    // Check for errors first
    if (!areVariantKeysValid) {
        return 'All variants must have a key'
    }
    if (hasDuplicateKeys) {
        return 'Variant keys must be unique'
    }

    // Build the display string
    const display =
        count === 2
            ? variants.map((v) => `${v.key} (${v.rollout_percentage || 0}%)`).join(' vs ')
            : `${count} variants (${variants.map((v) => `${v.rollout_percentage || 0}%`).join('/')})`

    // Append rollout error if needed
    return !isValidRollout ? `${display} • Total: ${totalRollout}% (must be 100%)` : display
}
