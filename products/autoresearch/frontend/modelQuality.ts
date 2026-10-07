/** A model at or above this AUC ranks people well enough to act on. */
export const STRONG_AUC_THRESHOLD = 0.8
/** A model at or above this AUC, and below the strong threshold, ranks people better than chance but loosely. */
export const FAIR_AUC_THRESHOLD = 0.7

export type ModelQualityLevel = 'strong' | 'fair' | 'weak'

export interface ModelQuality {
    level: ModelQualityLevel
    auc: number
    /** Realized AUC measures real outcomes, so it wins over holdout AUC whenever it exists. */
    source: 'realized' | 'holdout'
}

export const MODEL_QUALITY_LABEL: Record<ModelQualityLevel, string> = {
    strong: 'Strong',
    fair: 'Fair',
    weak: 'Weak',
}

export function modelQualityLevel(auc: number): ModelQualityLevel {
    if (auc >= STRONG_AUC_THRESHOLD) {
        return 'strong'
    }
    if (auc >= FAIR_AUC_THRESHOLD) {
        return 'fair'
    }
    return 'weak'
}

export function modelQuality(
    holdoutAuc: number | null | undefined,
    realizedAuc: number | null | undefined
): ModelQuality | null {
    if (realizedAuc != null) {
        return { level: modelQualityLevel(realizedAuc), auc: realizedAuc, source: 'realized' }
    }
    if (holdoutAuc != null) {
        return { level: modelQualityLevel(holdoutAuc), auc: holdoutAuc, source: 'holdout' }
    }
    return null
}

/** Plain-language reading of lift at 10%, or null when no validated date has measured it yet. */
export function liftSentence(liftAt10: number | null | undefined): string | null {
    if (liftAt10 == null) {
        return null
    }
    return `The top 10% of people by score did the target ${liftAt10.toFixed(1)}x as often as average.`
}
