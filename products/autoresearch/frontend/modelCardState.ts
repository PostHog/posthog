import { AutoresearchPipelineApi } from './generated/api.schemas'

export type ModelCardState = 'training' | 'draft' | 'scored'

/** A live training run wins over the status, so a retrain of a live model shows its progress. */
export function modelCardState({
    status,
    live_training_run,
}: Pick<AutoresearchPipelineApi, 'status' | 'live_training_run'>): ModelCardState {
    if (live_training_run || status === 'bootstrapping') {
        return 'training'
    }
    return status === 'draft' ? 'draft' : 'scored'
}
