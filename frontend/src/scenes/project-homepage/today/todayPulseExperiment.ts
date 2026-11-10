import type { HighlightExperimentResultApi } from 'products/today/frontend/generated/api.schemas'

import type { TodayTone } from './todayTone'

export const EXPERIMENT_PIN_REASON = "Experiments can't be pinned"

export function isExperimentKey(key: string): boolean {
    return key.startsWith('experiment:')
}

export function experimentLiftDecimals(lift: number): number {
    const size = Math.abs(lift)
    return size < 1 ? 2 : size < 10 ? 1 : 0
}

export function experimentTone(experiment: HighlightExperimentResultApi): TodayTone {
    if (!experiment.significant) {
        return 'neutral'
    }
    return experiment.favorable ? 'good' : 'risk'
}

export function experimentComparison(experiment: HighlightExperimentResultApi): string {
    return experiment.variants > 1 ? `${experiment.variant} vs ${experiment.control}` : `vs ${experiment.control}`
}

export function experimentVerdict(experiment: HighlightExperimentResultApi): string {
    return experiment.significant ? 'Significant' : 'Not significant'
}

export function experimentPeople(experiment: HighlightExperimentResultApi): string {
    return `${experiment.people.toLocaleString('en-US')} ${experiment.people === 1 ? 'person' : 'people'}`
}
