import { AutoresearchPipelineApi } from './generated/api.schemas'

/** The question a model answers, in plain words. The model list cards and the detail header both show it. */
export function pipelineQuestion({
    target_event,
    horizon_days,
}: Pick<AutoresearchPipelineApi, 'target_event' | 'horizon_days'>): string {
    if (!horizon_days) {
        return `Who will do ${target_event}?`
    }
    return horizon_days === 1
        ? `Who will do ${target_event} in the next day?`
        : `Who will do ${target_event} in the next ${horizon_days} days?`
}
