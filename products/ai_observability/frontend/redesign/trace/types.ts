export type TraceNodeKind = 'trace' | 'span' | 'generation' | 'embedding'

export type TraceMode = 'spans' | 'thread' | 'timeline'

export type NodeDetailTab = 'messages' | 'details' | 'evals' | 'raw'

export interface NodeStats {
    costUsd: number | null
    inputTokens: number | null
    outputTokens: number | null
    cacheReadTokens: number | null
    latencyMs: number | null
}

export interface TraceTreeNode {
    id: string
    kind: TraceNodeKind
    name: string
    model: string | null
    stats: NodeStats
    hasError: boolean
    children: TraceTreeNode[]
}

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

export type EvalVerdict = 'pass' | 'fail' | 'na'

export interface EvalResult {
    id: string
    name: string
    verdict: EvalVerdict
    reasoning: string | null
}

export type EvalsState =
    | { status: 'loading' }
    | { status: 'ready'; results: EvalResult[] }
    | { status: 'error'; errorMessage: string }

export interface PersonLink {
    label: string
    href: string
}

export interface TimelineRowData {
    id: string
    kind: TraceNodeKind
    name: string
    depth: number
    startMs: number
    durationMs: number | null
}
