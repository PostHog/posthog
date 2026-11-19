import { FeatureImportanceApi } from './generated/api.schemas'
import { eventName } from './pipelineQuestion'

/**
 * AUC cutoffs for the quality verdict: Strong at or above `strong`, Fair at or above `fair`, Weak below.
 * They do not vary by base rate yet. Tune them here after dogfooding.
 */
export const MODEL_QUALITY_THRESHOLDS = {
    strong: 0.8,
    fair: 0.7,
} as const

/** A top driver at least this many times as important as the second driver makes the model lean on one signal. */
export const DOMINANT_DRIVER_RATIO = 3

/** Measured lift lands a little below the exact ceiling, for example 4.94 against 5 at the top 20%. */
const LIFT_CEILING_TOLERANCE = 0.97

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

/** Two decimals, or three from 0.995 up, so that an AUC below 1 never shows as 1.00. */
export function formatAuc(auc: number): string {
    if (auc >= 1 || auc < 0.995) {
        return auc.toFixed(2)
    }
    return Math.min(Number(auc.toFixed(3)), 0.999).toFixed(3)
}

/** Lift peaks when everyone who did the target is in the top share, or everyone in the top share did it. */
function liftCeiling(share: number, baseRate?: number | null): number {
    return baseRate != null && baseRate > share ? 1 / baseRate : 1 / share
}

export function isLiftAtCeiling(lift: number, share: number, baseRate?: number | null): boolean {
    return lift >= liftCeiling(share, baseRate) * LIFT_CEILING_TOLERANCE
}

export function liftCeilingNote(share: number, baseRate?: number | null): string {
    const ceiling = Number(liftCeiling(share, baseRate).toFixed(1))
    return `This lift is near its maximum, because the top ${Math.round(share * 100)}% can get at most ${ceiling}×.`
}

/** The top feature when its importance is at least `DOMINANT_DRIVER_RATIO` times the second feature's. */
export function dominantDriver(features: readonly FeatureImportanceApi[] | undefined): string | null {
    const [first, second] = [...(features ?? [])].sort((a, b) => b.importance - a.importance)
    if (!first || !second || first.importance <= 0) {
        return null
    }
    return first.importance >= DOMINANT_DRIVER_RATIO * second.importance ? first.name : null
}

function liftSentence(liftAt10: number | null | undefined, target: string, confirmed: boolean): string {
    if (liftAt10 == null) {
        // A confirmed model has realized metrics, so the API leaves lift null only when no one did the target that day.
        // An unconfirmed model card shows its Likely count instead, so this line is the fallback for a card without one.
        return confirmed
            ? `No one did ${eventName(target)} in the latest check`
            : 'Not checked against real outcomes yet'
    }
    if (isLiftAtCeiling(liftAt10, 0.1)) {
        return `Nearly everyone who did ${eventName(target)} was in the top 10%`
    }
    return `Top 10% are ${liftAt10.toFixed(1)}× more likely to do ${eventName(target)}`
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
