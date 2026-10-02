import type { TraceNodeApi } from '../../generated/api.schemas'

export type TraceNodeKind = TraceNodeApi['kind']

export type TraceMode = 'spans' | 'thread' | 'timeline'

export type NodeDetailTab = 'messages' | 'details' | 'evals' | 'raw'

export type MessageRole = 'system' | 'user' | 'assistant' | 'tool'

export type AttachmentMediaType = 'image' | 'audio' | 'video' | 'file'

export type MessagePart =
    | { kind: 'text'; text: string }
    | { kind: 'thinking'; text: string }
    | { kind: 'toolCall'; name: string; args: unknown; result?: unknown; isError?: boolean }
    | {
          kind: 'attachment'
          mediaType: AttachmentMediaType
          name: string | null
          mimeType: string | null
          url: string | null
      }

export interface ThreadMessage {
    id: string
    role: MessageRole
    parts: MessagePart[]
    isInternal: boolean
    sourceNodeId: string | null
}

export interface ConversationTurn {
    id: string
    timestamp: string
    messages: ThreadMessage[]
    error: string | null
}

export type ConversationState =
    | { status: 'loading' }
    | { status: 'ready'; turns: ConversationTurn[]; activeTurnId: string | null }

export type NodeContent =
    | { kind: 'messages'; input: ThreadMessage[]; output: ThreadMessage[] }
    | { kind: 'io'; input: unknown; output: unknown }
    | { kind: 'loading' }
    | { kind: 'error'; message: string }

export interface NodeProperties {
    timestamp: string
    provider: string | null
    temperature: number | null
    sessionId: string | null
    promptName: string | null
    promptVersion: number | null
    person: string | null
}

/**
 * `unrated` is a result with a value but no verdict, such as a numeric score without a passing rule.
 * `inconclusive` is a run that produced no usable value: skipped, not applicable, no score, unknown sentiment.
 */
export type EvalOutcome = 'pass' | 'fail' | 'error' | 'pending' | 'inconclusive' | 'unrated'

export interface EvalTarget {
    label: string
    nodeId: string
}

export interface EvalResult {
    id: string
    name: string
    href: string | null
    outcome: EvalOutcome
    /** What the result says, such as "True", "0.82", "Positive" or "Skipped". */
    label: string
    reasoning: string | null
    timestamp: string
    isBackfill: boolean
    /** Null when the result targets the node being viewed. */
    target: EvalTarget | null
}

export type EvalsState =
    | { status: 'loading' }
    | { status: 'ready'; results: EvalResult[] }
    | { status: 'error'; errorMessage: string }

export interface LabeledLink {
    label: string
    href: string
}
