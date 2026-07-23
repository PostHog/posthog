import { Pool } from 'pg'

import { ParkedAction, WakeOutcome, applyResumeToState, wakeParkedJob } from '../parked-jobs/resume'
import { LlmStepCompletion, LlmStepError } from './llm-step.types'

export { WakeOutcome } from '../parked-jobs/resume'

// The LLM step is the first caller of the generic park-and-resume primitive (parked-jobs/resume).
// It writes its completion/error under `llmResult`/`llmError`, guarded by the dispatch nonce it
// stashed on the parked step as `llmRequestId`, so a redelivered/duplicate completion can't wake a
// later attempt of the same step. After a timeout advance the nonce is gone (or a re-dispatch minted
// a new one), so an old completion is correctly dropped.
export function applyLlmOutcomeToState(
    stateBuffer: Buffer,
    args: { nonce: string; completion?: LlmStepCompletion; error?: LlmStepError }
): Buffer | null {
    return applyResumeToState(stateBuffer, (currentAction: ParkedAction) => {
        if (currentAction.llmRequestId !== args.nonce) {
            return false
        }
        if (args.completion) {
            currentAction.llmResult = args.completion
        } else if (args.error) {
            currentAction.llmError = args.error
        } else {
            return false
        }
        return true
    })
}

// Wakes exactly one parked LLM job by id, delegating the race-safe wake to the generic primitive and
// supplying the LLM-specific state write.
export async function wakeParkedLlmJob(
    pool: Pick<Pool, 'connect'>,
    args: { jobId: string; actionId: string; nonce: string; completion?: LlmStepCompletion; error?: LlmStepError }
): Promise<WakeOutcome> {
    return wakeParkedJob(pool, {
        jobId: args.jobId,
        actionId: args.actionId,
        applyOutcome: (stateBuffer) =>
            applyLlmOutcomeToState(stateBuffer, {
                nonce: args.nonce,
                completion: args.completion,
                error: args.error,
            }),
    })
}
