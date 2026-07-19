import { DateTime } from 'luxon'

import { HogFlowAction } from '~/cdp/schema/hogflow'
import { LlmRateLimiter, NoopLlmRateLimiter } from '~/cdp/services/llm/llm-rate-limiter'
import { LlmRenderedMessage, LlmStepCompletion, LlmStepRequest } from '~/cdp/services/llm/llm-step.types'
import { HogFunctionInvocationGlobalsWithInputs } from '~/cdp/types'
import { LiquidRenderer } from '~/cdp/utils/liquid'
import { UUIDT } from '~/common/utils/utils'

import { CyclotronJobInvocationHogFlow } from '../../../types'
import { findContinueAction, findNextAction } from '../hogflow-utils'
import { ActionHandler, ActionHandlerOptions, ActionHandlerResult } from './action.interface'
import { calculatedScheduledAt } from './delay'

type LlmAction = Extract<HogFlowAction, { type: 'llm' }>

// The error/timeout branch, if the author wired one: a `branch` edge with index 0 out of the LLM
// step. When present, a failed or timed-out call routes there so the workflow can fall back (retry,
// rules path, notify a human). When absent, the step falls through to on_error (continue / abort).
function findErrorBranch(invocation: CyclotronJobInvocationHogFlow, action: LlmAction): HogFlowAction | undefined {
    const hasErrorBranch = invocation.hogFlow.edges.some(
        (edge) => edge.from === action.id && edge.type === 'branch' && edge.index === 0
    )
    return hasErrorBranch ? findNextAction(invocation.hogFlow, action.id, 0) : undefined
}

// Thrown when the timeout backstop fires without a completion. Surfaced through the executor's
// on_error handling (continue / abort), same as any other step error.
export class LlmStepTimeoutError extends Error {
    constructor(maxWaitDuration: string) {
        super(`LLM step timed out after ${maxWaitDuration} without a response`)
        this.name = 'LlmStepTimeoutError'
    }
}

// Cap what we write into workflow variables - trackActionResult throws above 5KB total. The MVP
// truncates; the RFC's object-storage spill (keep the full text by reference) is the follow-up.
const MAX_STORED_TEXT = 4000

// Generic LLM step. On entry it renders the prompt, dispatches the request to the cdp-llm-executor
// fleet (via result.llmRequests, which the worker flushes AFTER the parked job is persisted), and
// parks until the timeout backstop. It is woken early by the executor writing a completion (or a
// terminal error) into the step's state; a plain timeout dequeue takes the on_error path.
export class LlmActionHandler implements ActionHandler {
    constructor(private rateLimiter: LlmRateLimiter = new NoopLlmRateLimiter()) {}

    public async execute({
        invocation,
        action,
        result,
    }: ActionHandlerOptions<LlmAction>): Promise<ActionHandlerResult> {
        const currentAction = invocation.state.currentAction
        if (!currentAction) {
            throw new Error('LLM step executed without a current action')
        }

        // Resume paths first - the executor woke us by writing into state.

        // Terminal error: take the error branch if wired, else fall through to on_error handling.
        if (currentAction.llmError) {
            const error = currentAction.llmError
            currentAction.llmError = undefined
            currentAction.llmRequestId = undefined
            const errorBranch = findErrorBranch(invocation, action)
            if (errorBranch) {
                return { nextAction: errorBranch, result: { error: error.message } }
            }
            throw new Error(`LLM step failed: ${error.message}`)
        }

        // Completion: advance to the next step, storing the result into workflow variables.
        if (currentAction.llmResult) {
            const completion = currentAction.llmResult
            currentAction.llmResult = undefined
            currentAction.llmRequestId = undefined
            return {
                nextAction: findContinueAction(invocation),
                result: shapeCompletionForVariables(completion),
            }
        }

        // Already dispatched and re-entered with no result: the timeout backstop fired.
        if (currentAction.llmRequestId) {
            currentAction.llmRequestId = undefined
            const errorBranch = findErrorBranch(invocation, action)
            if (errorBranch) {
                return { nextAction: errorBranch, result: { timedOut: true } }
            }
            throw new LlmStepTimeoutError(action.config.max_wait_duration)
        }

        // Fresh entry. Enforce the rate/spend guardrail before dispatching - an over-cap call takes
        // the error branch (or on_error) instead of running up spend.
        const decision = await this.rateLimiter.check({
            teamId: invocation.teamId,
            workflowId: invocation.hogFlow.id,
            maxCallsPerMinute: action.config.max_calls_per_minute,
        })
        if (!decision.allowed) {
            const errorBranch = findErrorBranch(invocation, action)
            if (errorBranch) {
                return { nextAction: errorBranch, result: { rateLimited: true, reason: decision.reason } }
            }
            throw new Error(`LLM step blocked by rate limit: ${decision.reason}`)
        }

        // Render, dispatch, park.
        const nonce = new UUIDT().toString()
        const request: LlmStepRequest = {
            jobId: invocation.id,
            teamId: invocation.teamId,
            hogFlowId: invocation.hogFlow.id,
            actionId: action.id,
            nonce,
            model: action.config.model,
            messages: renderMessages(invocation, action),
            responseFormat: action.config.response_format,
            jsonSchema: action.config.json_schema,
            temperature: action.config.temperature,
            maxTokens: action.config.max_tokens,
            topP: action.config.top_p,
            reasoningEffort: action.config.reasoning_effort,
            thinking: action.config.thinking,
            tools: action.config.tools,
        }

        currentAction.llmRequestId = nonce
        currentAction.llmDispatchedAt = DateTime.now().toMillis()
        // Attach the dispatch to the result. The worker flushes result.llmRequests AFTER persisting
        // the parked job, so the executor can never wake a row that isn't parked yet.
        result.llmRequests = [...(result.llmRequests ?? []), request]

        return {
            // Park until the backstop. calculatedScheduledAt returns null only if it has already
            // elapsed (not expected on fresh entry); fall back to now so we never park forever.
            scheduledAt:
                calculatedScheduledAt(action.config.max_wait_duration, currentAction.startedAtTimestamp) ??
                DateTime.now(),
        }
    }
}

// Renders each message's content against workflow state. Liquid templating (`{{ variables.x }}`,
// `{{ event.properties.y }}`) reuses the shared LiquidRenderer; raw strings pass through. (Hog
// bytecode templating is a follow-up - liquid covers the MVP.)
function renderMessages(invocation: CyclotronJobInvocationHogFlow, action: LlmAction): LlmRenderedMessage[] {
    const globals = {
        event: invocation.state.event,
        person: invocation.person,
        groups: invocation.groups ?? {},
        variables: invocation.state.variables ?? {},
    } as unknown as HogFunctionInvocationGlobalsWithInputs

    return action.config.messages.map((message) => {
        const content = message.content
        let text = ''
        if (typeof content?.value === 'string') {
            text =
                content.templating === 'liquid'
                    ? LiquidRenderer.renderWithHogFunctionGlobals(content.value, globals)
                    : content.value
        } else if (content?.value != null) {
            text = JSON.stringify(content.value)
        }
        return { role: message.role, content: text }
    })
}

function shapeCompletionForVariables(completion: LlmStepCompletion): unknown {
    return {
        text: completion.text.length > MAX_STORED_TEXT ? completion.text.slice(0, MAX_STORED_TEXT) : completion.text,
        parsed: completion.parsed,
        model: completion.model,
    }
}
