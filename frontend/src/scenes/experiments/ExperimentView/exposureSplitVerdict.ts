import { humanFriendlyNumber } from 'lib/utils/numbers'

import { SampleRatioMismatch, SrmCause } from '~/queries/schema/schema-general'

// Mirrors SRM_SIGNIFICANCE_P_VALUE in products/experiments/backend/analysis_health.py, which
// decides whether the backend attaches a diagnosis.
export const SRM_SIGNIFICANCE_P_VALUE = 0.001

export interface ExposureSplitVerdict {
    isMismatch: boolean
    /** Short label for the collapsed exposures header. */
    label: string
    /** What the check found. */
    headline: string
    /** Why it most likely happened, or null when nothing narrowed it down. */
    cause: string | null
    /** What to do about it, or null when there is nothing to do. */
    nextStep: string | null
    /** Whether the cause points at the exposure criteria, so offering to edit them helps. */
    suggestsExposureCriteriaFix: boolean
}

const MATCHES_ROLLOUT: ExposureSplitVerdict = {
    isMismatch: false,
    label: 'Split matches rollout',
    headline: 'Exposures match your rollout percentages.',
    cause: 'The gap between actual and expected exposures is within normal random variation.',
    nextStep: null,
    suggestsExposureCriteriaFix: false,
}

function describeCause(
    mismatch: SampleRatioMismatch
): Pick<ExposureSplitVerdict, 'cause' | 'nextStep' | 'suggestsExposureCriteriaFix'> {
    const diagnosis = mismatch.diagnosis

    if (diagnosis?.cause === SrmCause.LowSampleSize) {
        const smallestVariant = humanFriendlyNumber(diagnosis.smallest_expected_count ?? 0)
        return {
            cause: `There aren't many exposures yet. Your rollout expects about ${smallestVariant} users in its smallest variant, and at that size the split swings around on its own.`,
            nextStep: 'Check back once each variant has a few thousand exposures.',
            suggestsExposureCriteriaFix: false,
        }
    }

    if (diagnosis?.cause === SrmCause.CaptureBySurface && diagnosis.surface_skew) {
        const { surface, variant, variant_percentage, expected_percentage } = diagnosis.surface_skew
        return {
            cause: `On ${surface}, ${variant} takes ${variant_percentage.toFixed(0)}% of first exposures, where your rollout expects ${expected_percentage.toFixed(0)}%. Other pages do match your rollout, so it looks like only ${variant} users reach ${surface}.`,
            nextStep: `Check that your exposure event fires for every variant, on every page in the experiment. If it only fires on ${surface}, users in the other variants are never counted.`,
            suggestsExposureCriteriaFix: true,
        }
    }

    return {
        cause: null,
        nextStep:
            'Check whether your exposure event can fire before flags have loaded, since those users are dropped from their variant. Then check that no release condition pins a variant instead of randomizing.',
        suggestsExposureCriteriaFix: false,
    }
}

/**
 * Turns the backend's chi-squared result into something a reader can act on. The verdict is
 * the same in both directions, so a matching split says so rather than saying nothing.
 */
export function getExposureSplitVerdict(mismatch: SampleRatioMismatch | undefined): ExposureSplitVerdict | null {
    if (mismatch == null) {
        return null
    }
    if (mismatch.p_value >= SRM_SIGNIFICANCE_P_VALUE) {
        return MATCHES_ROLLOUT
    }

    return {
        isMismatch: true,
        label: 'Uneven split',
        headline: "Exposures don't match your rollout percentages.",
        ...describeCause(mismatch),
    }
}
