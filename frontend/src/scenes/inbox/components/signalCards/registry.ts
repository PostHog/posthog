import { ConversationsTicketSignalCard, conversationsTicketSignalCardEntry } from './ConversationsTicketSignalCard'
import {
    EndpointExecutionFailedSignalCard,
    endpointExecutionFailedSignalCardEntry,
} from './EndpointExecutionFailedSignalCard'
import { ErrorTrackingSignalCard, errorTrackingSignalCardEntry } from './ErrorTrackingSignalCard'
import { GithubIssueSignalCard, githubIssueSignalCardEntry } from './GithubIssueSignalCard'
import { HealthCheckSignalCard, healthCheckSignalCardEntry } from './HealthCheckSignalCard'
import { LinearIssueSignalCard, linearIssueSignalCardEntry } from './LinearIssueSignalCard'
import {
    LlmEvalReportSignalCard,
    LlmEvalTraceSignalCard,
    llmEvalReportSignalCardEntry,
    llmEvalTraceSignalCardEntry,
} from './LlmAnalyticsSignalCard'
import { LogsAlertSignalCard, logsAlertSignalCardEntry } from './LogsAlertSignalCard'
import { PgAnalyzeSignalCard, pgAnalyzeSignalCardEntry } from './PgAnalyzeSignalCard'
import { SessionReplaySignalCard, sessionReplaySignalCardEntry } from './SessionReplaySignalCard'
import { SignalsScoutSignalCard, signalsScoutSignalCardEntry } from './SignalsScoutSignalCard'
import type { SignalCardEntry } from './types'
import { ZendeskTicketSignalCard, zendeskTicketSignalCardEntry } from './ZendeskTicketSignalCard'

// Re-export every per-source card so consumers (stories, tests) can reach them by name.
export {
    ConversationsTicketSignalCard,
    EndpointExecutionFailedSignalCard,
    ErrorTrackingSignalCard,
    GithubIssueSignalCard,
    HealthCheckSignalCard,
    LinearIssueSignalCard,
    LlmEvalReportSignalCard,
    LlmEvalTraceSignalCard,
    LogsAlertSignalCard,
    PgAnalyzeSignalCard,
    SessionReplaySignalCard,
    SignalsScoutSignalCard,
    ZendeskTicketSignalCard,
}

/**
 * Ordered list of signal-card renderers. `SignalCard` picks the first entry whose `matches`
 * returns true. Every entry gates on `source_product`, so entries are mutually exclusive and
 * order is not load-bearing — but keep richer/more-specific variants first as a safety net.
 */
export const SIGNAL_CARD_REGISTRY: SignalCardEntry[] = [
    // PostHog products with live embeds
    errorTrackingSignalCardEntry,
    sessionReplaySignalCardEntry,
    // LLM analytics: report variant first (mutually exclusive guards, but explicit)
    llmEvalReportSignalCardEntry,
    llmEvalTraceSignalCardEntry,
    // Other PostHog-native products
    healthCheckSignalCardEntry,
    conversationsTicketSignalCardEntry,
    endpointExecutionFailedSignalCardEntry,
    logsAlertSignalCardEntry,
    signalsScoutSignalCardEntry,
    // External sources
    githubIssueSignalCardEntry,
    linearIssueSignalCardEntry,
    zendeskTicketSignalCardEntry,
    pgAnalyzeSignalCardEntry,
]
