import type {
    TraceAttachmentPartApi,
    TraceEvaluationResultOutcomeEnumApi,
    TraceMessageApi,
    TraceNodeApi,
    TraceNodeContentApi,
    TraceNodeDetailApi,
    TraceNodeRawApi,
    TraceNodeEvaluationRollupOutcomeEnumApi,
    TraceSummaryContentApi,
    TraceSurveyResponseApi,
} from '../../generated/api.schemas'

export type TraceNodeKind = TraceNodeApi['kind']

export type TraceMode = 'spans' | 'thread' | 'timeline' | 'summary' | 'feedback'
export type TraceOpeningMode = 'summary' | null

export type NodeDetailTab = 'messages' | 'details' | 'evals' | 'raw'

export type LoadFailure = 'not_found' | 'failed'

/**
 * `selection` is a click on a step. `navigation` is a node the view selects without a click: on open, from a
 * link, as the default node, as the root while the trace loads, or from the browser history.
 */
export type NodeLoadTrigger = 'selection' | 'navigation' | 'prefetch' | 'thread'

export type NodeLoad =
    | { status: 'loading' }
    | { status: 'ready'; node: TraceNodeDetailApi }
    | { status: 'error'; failure: LoadFailure }

export type RawLoad =
    | { status: 'loading' }
    | { status: 'ready'; raw: TraceNodeRawApi }
    | { status: 'error'; failure: LoadFailure }

export type MessageRole = TraceMessageApi['role']

/** Which messages of a step open first: from the last user message on, or all of them. */
export type MessagesOpening = 'lastTurn' | 'everything'

export type AttachmentMediaType = TraceAttachmentPartApi['mediaType']

export type MessagePart = TraceMessageApi['parts'][number]

export type ThreadMessage = TraceMessageApi

export interface ConversationTurn {
    id: string
    timestamp: string
    input: NodeSideContent
    output: NodeSideContent
    error: string | null
}

export type ConversationState =
    | { status: 'loading' }
    | { status: 'error'; message: string }
    | { status: 'ready'; turns: ConversationTurn[]; activeTurnId: string | null }

export type NodeSideContent = TraceNodeContentApi['input']

/**
 * `unrated` is a result with a value but no verdict, such as a numeric score without a passing rule.
 * `inconclusive` is a run that produced no usable value: skipped, not applicable, no score, unknown sentiment.
 */
export type EvalOutcome = TraceEvaluationResultOutcomeEnumApi

/** A step's evaluations rolled up: `fail` if any fails, else `pass` if any passes, else `unrated`. */
export type EvalRollupOutcome = TraceNodeEvaluationRollupOutcomeEnumApi

export interface LabeledLink {
    label: string
    href: string
}

export type TraceSearchStatus = 'idle' | 'loading' | 'ready' | 'error'

export type TraceSearchFailure = 'too_slow' | 'failed'

export type MatchDirection = 'next' | 'previous'

export type SummaryItemKind = 'bullet' | 'note'

/** Why a summary request failed. `throttled` means the user reached their summary limit. */
export type SummaryRequestError = 'throttled' | 'failed'

/** `none` means no summary this user may see exists yet, and `error` that reading it failed. A `failed` summary that
 * is not `retryable` fails the same way on every new request. */
export type SummaryModeState =
    | { status: 'loading' }
    | { status: 'none' }
    | { status: 'pending' }
    | { status: 'ready'; summary: TraceSummaryContentApi }
    | { status: 'failed'; message: string; retryable: boolean }
    | { status: 'error' }

/** Where a person opened the Feedback mode from, other than its tab. */
export type FeedbackEntry = 'chip' | 'step'

export type SurveyAnswer = TraceSurveyResponseApi['answers'][number]

/** What the Feedback mode needs to place an entry: on a step of the tree, or on the whole trace, and which step it was
 * opened from. */
export interface FeedbackStepContext {
    traceId: string
    stepLabels: ReadonlyMap<string, string>
    focusNodeId: string | null
}
