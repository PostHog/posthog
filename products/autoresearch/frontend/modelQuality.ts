/**
 * AUC cutoffs for the quality verdict: Strong at or above `strong`, Fair at or above `fair`, Weak below.
 * They do not vary by base rate yet. Tune them here after dogfooding.
 */
export const MODEL_QUALITY_THRESHOLDS = {
    strong: 0.8,
    fair: 0.7,
} as const

export type ModelQualityVerdict = 'Strong' | 'Fair' | 'Weak'

/** `confirmed` when the verdict comes from realized AUC, `testing only` when it comes from holdout AUC. */
export type ModelQualityBasis = 'confirmed' | 'testing only'

export interface ModelQuality {
    verdict: ModelQualityVerdict
    basis: ModelQualityBasis
    auc: number
    sentence: string
}

export interface ModelQualityInput {
    holdoutAuc: number | null | undefined
    realizedAuc: number | null | undefined
    liftAt10: number | null | undefined
    isPreliminary: boolean | null | undefined
    target: string
}

function modelQualityVerdict(auc: number): ModelQualityVerdict {
    if (auc >= MODEL_QUALITY_THRESHOLDS.strong) {
        return 'Strong'
    }
    if (auc >= MODEL_QUALITY_THRESHOLDS.fair) {
        return 'Fair'
    }
    return 'Weak'
}

function liftSentence(liftAt10: number | null | undefined, target: string, confirmed: boolean): string {
    if (liftAt10 == null) {
        // A confirmed model has realized metrics, so the API leaves lift null only when no one did the target that day.
        return confirmed ? `No one did ${target} in the latest check` : 'Not checked against real outcomes yet'
    }
    return `Top 10% are ${liftAt10.toFixed(1)}× more likely to do ${target}`
}

/** Realized AUC measures real outcomes, so it wins over holdout AUC. Null when the model has no AUC at all. */
export function modelQuality({
    holdoutAuc,
    realizedAuc,
    liftAt10,
    isPreliminary,
    target,
}: ModelQualityInput): ModelQuality | null {
    const confirmed = realizedAuc != null && !isPreliminary
    const auc = confirmed ? realizedAuc : holdoutAuc
    if (auc == null) {
        return null
    }
    return {
        verdict: modelQualityVerdict(auc),
        basis: confirmed ? 'confirmed' : 'testing only',
        auc,
        sentence: liftSentence(liftAt10, target, confirmed),
    }
}
