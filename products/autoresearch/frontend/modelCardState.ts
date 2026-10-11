import { Dayjs, dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils/strings'

import { AutoresearchPipelineApi } from './generated/api.schemas'

export type ModelCardState = 'draft' | 'training' | 'awaiting_check' | 'confirmed'

/**
 * A live training run shows its progress only while the model has no champion. A retrain of a
 * model with a champion keeps the champion's body, and the card adds a retraining strip.
 */
export function modelCardState({
    status,
    live_training_run,
    champion_holdout_auc,
    champion_realized_auc,
    champion_is_preliminary,
}: Pick<
    AutoresearchPipelineApi,
    'status' | 'live_training_run' | 'champion_holdout_auc' | 'champion_realized_auc' | 'champion_is_preliminary'
>): ModelCardState {
    const hasChampion = champion_holdout_auc != null || champion_realized_auc != null
    if (!hasChampion && (live_training_run || status === 'bootstrapping')) {
        return 'training'
    }
    if (status === 'draft') {
        return 'draft'
    }
    // The same rule as the `confirmed` basis in modelQuality: a preliminary realized AUC is not a confirmation.
    return champion_realized_auc != null && !champion_is_preliminary ? 'confirmed' : 'awaiting_check'
}

/** Horizons up to this many days count down in days. Longer horizons show the date. */
const COUNTDOWN_MAX_DAYS = 14

export interface FirstCheckCountdown {
    label: string
    /** How much of the outcome window has passed, from 0 to 100. */
    percent: number
}

export function firstCheckCountdown(
    firstCheckExpectedAt: string,
    horizonDays: number,
    now: Dayjs = dayjs()
): FirstCheckCountdown {
    const checkAt = dayjs(firstCheckExpectedAt)
    const hoursLeft = checkAt.diff(now, 'hour', true)
    const percent = Math.min(100, Math.max(0, 100 * (1 - hoursLeft / (horizonDays * 24))))
    if (hoursLeft <= 0) {
        return { label: 'First real check is due', percent }
    }
    const daysLeft = Math.ceil(hoursLeft / 24)
    return {
        label:
            horizonDays <= COUNTDOWN_MAX_DAYS
                ? `First real check in ${pluralize(daysLeft, 'day')}`
                : `First real check on ${checkAt.format('MMM D')}`,
        percent,
    }
}
