import type { WorkOptionApi, WorkRunApiParams, WorkStepApi } from 'products/today/frontend/generated/api.schemas'

/** How a step reads in the frame. The frame works it out from the payload, so the server never sends it. */
export type WorkStepState = 'done' | 'needs_you' | 'waiting'

/** Runs an option whose run type is `action`. The host page owns the handler, because a handler is not data. */
export type WorkRunActionHandler = (
    actionId: string,
    params: WorkRunApiParams,
    option: WorkOptionApi,
    step: WorkStepApi
) => void
