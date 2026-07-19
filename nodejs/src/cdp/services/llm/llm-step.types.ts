// Shared types for the generic LLM workflow step.
//
// The step dispatches a request to the cdp-llm-executor fleet, parks the Cyclotron job, and is
// woken by id when the completion lands - see the "Generic LLM steps" RFC and
// services/hogflows/actions/llm.ts. These types are deliberately free of any heavy imports so
// core types (cdp/types.ts) can reference them without a cycle.

export type LlmMessageRole = 'system' | 'user' | 'assistant'

// A prompt message after templating has been rendered against workflow state.
export interface LlmRenderedMessage {
    role: LlmMessageRole
    content: string
}

// The request the workflow worker hands off to the executor fleet (via Kafka). It carries only
// what the executor needs to make the call and to wake the exact parked job back up.
//
// jobId is the cyclotron_jobs primary key of the parked run; actionId + nonce guard against waking
// a job that has since advanced (timeout won the race) or been re-dispatched (a redelivery).
// (Large prompts should be spilled to object storage and referenced here; the MVP inlines them.)
export interface LlmStepRequest {
    jobId: string
    teamId: number
    hogFlowId: string
    actionId: string
    nonce: string

    model: string
    messages: LlmRenderedMessage[]
    responseFormat?: 'text' | 'json_schema'
    jsonSchema?: unknown
    temperature?: number
    maxTokens?: number
    topP?: number
    reasoningEffort?: 'minimal' | 'low' | 'medium' | 'high'
    thinking?: boolean
    tools?: unknown[]
}

// The completion the gateway returns, normalized to what the step stores in workflow state.
// For json_schema responses `text` is the raw JSON string and `parsed` holds the decoded object.
export interface LlmStepCompletion {
    text: string
    parsed?: unknown
    model?: string
    usage?: { inputTokens?: number; outputTokens?: number }
    // Set when the full completion was spilled to object storage because it was too large to keep in
    // cyclotron_jobs.state. `text`/`parsed` are then a truncated preview; the full payload lives at
    // `ref` and is retrievable via the LlmBlobStore. Keeps the parked row small at scale.
    ref?: string
    byteSize?: number
    truncated?: boolean
}

// A terminal error the executor gave up on, written into state so the parked job's handler can
// take its on_error path immediately on resume instead of waiting out the full timeout.
export interface LlmStepError {
    message: string
    // Whether the executor exhausted its retries (true) vs. a non-retryable request error (false).
    retriable: boolean
}
