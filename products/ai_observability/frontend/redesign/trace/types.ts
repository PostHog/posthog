import type {
    TraceApi,
    TraceAttachmentPartApi,
    TraceEvaluationResultOutcomeEnumApi,
    TraceListItemApi,
    TraceMessageApi,
    TraceNodeApi,
    TraceNodeContentApi,
    TraceNodeDetailApi,
    TraceNodeRawApi,
    TraceNodeEvaluationRollupOutcomeEnumApi,
    TracePersonApi,
    TracePreviewMissingReasonApi,
    TraceSummaryContentApi,
    TraceSurveyResponseApi,
} from '../../generated/api.schemas'
import type { TraceCellStatus } from '../shared/cellLoads'

export type TraceNodeKind = TraceNodeApi['kind']

export type TraceMode = 'spans' | 'thread' | 'timeline' | 'summary' | 'feedback'
export type TraceOpeningMode = 'summary' | 'thread' | null

export type NodeDetailTab = 'messages' | 'details' | 'evals' | 'raw'

export type LoadFailure = 'not_found' | 'failed'

/**
 * `selection` is a click on a step. `navigation` is a node the view selects without a click: on open, from a
 * link, as the default node, as the root while the trace loads, or from the browser history.
 */
export type NodeLoadTrigger = 'selection' | 'keyboard' | 'navigation' | 'prefetch' | 'thread'

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
    /** How long the user waited for the answer, from the trace's latency; null when not shown. */
    waitMs: number | null
    /** Whether the wait counts as slow, as the read of the turn says. */
    waitSlow?: boolean
    /** How long the conversation was silent before the turn, when the read of the turn counts it as a silence. */
    silenceBeforeMs?: number | null
    input: NodeSideContent
    output: NodeSideContent
    error: string | null
    /** Why a side is empty or cut, when the read could not return all of it. */
    missingReasons?: TurnMissingReasons
    /** Whether the input and output have loaded, for a turn whose messages are read after the turn itself. */
    sidesStatus?: TraceCellStatus
    /** The turn's trace as a list of traces reads it, for a turn that is one of several. */
    trace?: Pick<TraceListItemApi, 'name' | 'totals'>
}

export interface TurnMissingReasons {
    input: TracePreviewMissingReasonApi | null
    output: TracePreviewMissingReasonApi | null
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

export type StepDirection = 'next' | 'previous'

export type MatchDirection = StepDirection

/** A move within the step tree: to a neighbour in drawn order, to either end, or along the hierarchy. */
export type TreeStep = StepDirection | 'first' | 'last' | 'parent' | 'child'

export type StepKeySource = 'shortcut' | 'arrow'

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

/** What a list row already knows about a trace, enough to paint the trace's header before the trace read answers. */
export type TraceOverview = Pick<
    TraceApi,
    | 'id'
    | 'name'
    | 'createdAt'
    | 'sessionId'
    | 'totals'
    | 'hasError'
    | 'errorCount'
    | 'totalsPartial'
    | 'costAndLatencyPartial'
>

export interface TraceSeed {
    overview: TraceOverview
    defaultStepId: string | null
    person?: TracePersonApi
}

export interface TraceViewKey {
    hostId: string
    traceId: string
    timestampHint: string | null
}
