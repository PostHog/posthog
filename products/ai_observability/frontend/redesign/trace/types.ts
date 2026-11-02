import type {
    TraceEvaluationResultOutcomeEnumApi,
    TraceFeedbackScoreApi,
    TraceFeedbackTextApi,
    TraceNodeApi,
    TraceNodeDetailApi,
    TraceNodeEvaluationRollupOutcomeEnumApi,
    TraceSummaryContentApi,
    TraceSurveyResponseApi,
    TraceUnansweredSurveyApi,
} from '../../generated/api.schemas'

export type TraceNodeKind = TraceNodeApi['kind']

export type TraceMode = 'spans' | 'thread' | 'timeline' | 'summary' | 'feedback'

export type TraceViewChoice = 'new' | 'legacy'

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
    | { status: 'error'; message: string }
    | { status: 'ready'; turns: ConversationTurn[]; activeTurnId: string | null }

export type NodeContent =
    | { kind: 'messages'; input: ThreadMessage[]; output: ThreadMessage[] }
    | { kind: 'io'; input: unknown; output: unknown }
    | { kind: 'loading' }
    | { kind: 'error'; message: string }

export interface NodeProperties {
    timestamp: string | null
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
export type EvalOutcome = TraceEvaluationResultOutcomeEnumApi

/** A step's evaluations rolled up: `fail` if any fails, else `pass` if any passes, else `unrated`. */
export type EvalRollupOutcome = TraceNodeEvaluationRollupOutcomeEnumApi

export interface EvalsChipData {
    passed: number
    /** Results with a pass or a fail. */
    graded: number
    unrated: number
}

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

export interface GitPullRequestLink {
    number: number
    title: string | null
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

export interface FeedbackStep {
    id: string
    name: string
}

/**
 * `step` is null for feedback on the whole trace, and for a step the tree does not hold. `focused` marks the entries
 * of the step the Feedback mode was opened from.
 */
export interface FeedbackPlacement {
    step: FeedbackStep | null
    focused: boolean
}

export type FeedbackScoreRow = TraceFeedbackScoreApi & FeedbackPlacement

/** Survey responses link to the whole trace, so their `step` is always null. */
export type FeedbackResponseItem = (TraceFeedbackTextApi | TraceSurveyResponseApi) & FeedbackPlacement

export type SurveyAnswer = TraceSurveyResponseApi['answers'][number]

export type FeedbackModeState =
    | { status: 'loading' }
    | { status: 'error' }
    | {
          status: 'ready'
          scores: FeedbackScoreRow[]
          responses: FeedbackResponseItem[]
          unanswered: TraceUnansweredSurveyApi[]
          surveysFailed: boolean
      }

export interface FeedbackChipData {
    total: number
    thumbsUp: number
    thumbsDown: number
}

export interface StepFeedback {
    scores: TraceFeedbackScoreApi[]
    responseCount: number
}
