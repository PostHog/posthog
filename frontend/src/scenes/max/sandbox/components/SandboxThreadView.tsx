import { useValues } from 'kea'
import { useMemo } from 'react'

import { IconWrench } from '@posthog/icons'

import { TaskExecutionStatus as ExecutionStatus } from '~/queries/schema/schema-assistant-messages'

import { SandboxActivity } from '../../components/Activity'
import { MarkdownMessage } from '../../MarkdownMessage'
import type { SandboxToolCallMessage } from '../../maxTypes'
import { AssistantFailureMessage } from '../../messages/AssistantFailureMessage'
import { MessageTemplate } from '../../messages/MessageTemplate'
import { ReasoningAnswer } from '../../messages/ReasoningAnswer'
import { sandboxStreamLogic } from '../../sandboxStreamLogic'
import type { SandboxProgressStep, ThreadItem as SandboxThreadItem } from '../../types/sandboxStreamTypes'
import { getRandomThinkingMessage } from '../../utils/thinkingMessages'
import { SandboxPullRequestCard } from '../SandboxPullRequestCard'
import { SandboxRunContext } from '../SandboxRunContext'
import { SandboxCompactBoundaryItem, SandboxStatusItem, SandboxTaskNotificationItem } from '../SandboxThreadItems'
import { resolveToolCall } from '../sandboxToolResolver'
import { SandboxToolCall } from './tool/SandboxToolCall'

/** Maps a raw merged `ToolInvocation` into the flat `SandboxToolCallMessage` the registry renderers read. */
function toolInvocationToMessage(
    invocation: ReturnType<typeof sandboxStreamLogic.values.toolInvocations.get>
): SandboxToolCallMessage | null {
    if (!invocation) {
        return null
    }
    const resolved = resolveToolCall(invocation)
    return {
        id: invocation.toolCallId,
        resolvedKey: resolved.resolvedKey,
        rawServerName: invocation.rawServerName,
        rawToolName: invocation.rawToolName,
        innerToolName: resolved.innerToolName,
        claudeToolName: resolved.claudeToolName,
        rawInput: invocation.input,
        innerInput: resolved.innerInput,
        rawOutput: invocation.output,
        content: invocation.contentBlocks,
        status: invocation.status,
        title: invocation.title,
        kind: invocation.kind,
        locations: invocation.locations,
        error: invocation.error,
    }
}

/**
 * Sandbox-runtime thread presenter. Reads `sandboxStreamLogic.values.threadItems` (assistant text,
 * tool-invocation references, run separators, inline errors) from whatever `sandboxStreamLogic`
 * instance is bound above it — a live PostHog AI conversation or a read-only run viewer — and
 * dispatches tool cards through the sandbox tool registry. Conversation-agnostic by design: it knows
 * only the bound stream logic, never langgraph vs sandbox or the conversation.
 */
export function SandboxThreadView(): JSX.Element {
    // Drive the thinking indicator from real agent progress: show the latest `_posthog/progress`
    // message while the run is active, falling back to the canned rotation.
    const {
        threadItems,
        toolInvocations,
        currentProgress,
        isThinking,
        streamPhase,
        runArtifacts,
        turnComplete,
        currentRunStatus,
    } = useValues(sandboxStreamLogic)
    const turnCancelled = currentRunStatus === 'cancelled'
    const hasActiveProgressItem = threadItems.some(
        (item) => item.type === 'progress' && item.progressSteps?.some((step) => step.status === 'in_progress')
    )

    return (
        <>
            {runArtifacts.branch && (
                <SandboxRunContext
                    branch={runArtifacts.branch}
                    baseBranch={runArtifacts.baseBranch}
                    repo={runArtifacts.repo}
                />
            )}
            {threadItems.map((item, index) => {
                if (item.type === 'human_message') {
                    return (
                        <MessageTemplate key={item.id} type="human">
                            <MarkdownMessage content={item.text || '*No text.*'} id={item.id} />
                        </MessageTemplate>
                    )
                }
                if (item.type === 'assistant_message') {
                    return (
                        <MessageTemplate key={item.id} type="ai">
                            <MarkdownMessage content={item.text ?? ''} id={item.id} />
                        </MessageTemplate>
                    )
                }
                if (item.type === 'assistant_thought') {
                    // Empty chunks prime the stream before any reasoning text arrives — skip them so
                    // a contentless "Thought" never shows; the bottom indicator covers that gap.
                    if (!item.text?.trim()) {
                        return null
                    }
                    // Collapse to "Thought" once a later block starts or the run stops thinking —
                    // mirrors the LangGraph thread's reasoning-complete rule.
                    const completed = index !== threadItems.length - 1 || !isThinking
                    return (
                        <ReasoningAnswer
                            key={item.id}
                            content={item.text}
                            id={item.id}
                            completed={completed}
                            showCompletionIcon={false}
                        />
                    )
                }
                if (item.type === 'tool_invocation' && item.toolCallId) {
                    const message = toolInvocationToMessage(toolInvocations.get(item.toolCallId))
                    if (!message) {
                        return null
                    }
                    return (
                        <SandboxToolCall
                            key={item.id}
                            message={message}
                            turnComplete={turnComplete}
                            turnCancelled={turnCancelled}
                        />
                    )
                }
                if (item.type === 'error') {
                    return <AssistantFailureMessage key={item.id} id={item.id} content={item.errorMessage} />
                }
                if (item.type === 'status') {
                    return <SandboxStatusItem key={item.id} item={item} />
                }
                if (item.type === 'compact_boundary') {
                    return <SandboxCompactBoundaryItem key={item.id} item={item} />
                }
                if (item.type === 'task_notification') {
                    return <SandboxTaskNotificationItem key={item.id} item={item} />
                }
                if (item.type === 'progress') {
                    return <SandboxProgressItem key={item.id} item={item} />
                }
                return null
            })}
            {streamPhase === 'thinking' && !hasActiveProgressItem && (
                <SandboxThinkingIndicator progress={currentProgress} />
            )}
            {/* Post-turn only: a reconnect refetch can fold in a pr_url mid-run, so gate on !isThinking. */}
            {!isThinking && runArtifacts.prUrl && (
                <SandboxPullRequestCard prUrl={runArtifacts.prUrl} branch={runArtifacts.branch} />
            )}
        </>
    )
}

function progressStepText(step: SandboxProgressStep): string {
    return step.detail ? `${step.label}\n\n${step.detail}` : step.label
}

function resolveSandboxProgressState(steps: SandboxProgressStep[]): ExecutionStatus {
    if (steps.some((step) => step.status === 'failed')) {
        return ExecutionStatus.Failed
    }
    if (steps.some((step) => step.status === 'in_progress')) {
        return ExecutionStatus.InProgress
    }
    if (steps.length > 0 && steps.every((step) => step.status === 'pending')) {
        return ExecutionStatus.Pending
    }
    return ExecutionStatus.Completed
}

function resolveSandboxProgressHeadline(steps: SandboxProgressStep[]): string {
    const active = steps.find((step) => step.status === 'in_progress')
    if (active) {
        return active.label
    }
    return steps.at(-1)?.label ?? 'Working'
}

function SandboxProgressItem({ item }: { item: SandboxThreadItem }): JSX.Element | null {
    const steps = item.progressSteps ?? []
    if (!steps.length) {
        return null
    }

    const headline = resolveSandboxProgressHeadline(steps)
    const substeps = steps.length > 1 ? steps.map(progressStepText) : []
    const state = resolveSandboxProgressState(steps)

    return (
        <SandboxActivity
            id={item.id}
            content={headline}
            substeps={substeps}
            state={state}
            icon={<IconWrench />}
            showCompletionIcon={true}
        />
    )
}

/**
 * Bottom-of-thread "what's it doing right now" line for sandbox conversations. Reflects the latest
 * `_posthog/progress` message when present, otherwise the canned thinking rotation.
 */
function SandboxThinkingIndicator({ progress }: { progress: string | null }): JSX.Element {
    // One roll per mount — re-rolling on every progress transition would visibly swap the verb.
    const fallbackMessage = useMemo(() => getRandomThinkingMessage(), [])
    const message = progress?.trim() ? progress : fallbackMessage
    // Match the LangGraph loader: a bubble-free reasoning line (muted brain icon + muted text),
    // static (no shimmer), via the shared Activity primitive — not a MessageTemplate bubble.
    return <ReasoningAnswer content={message} id="sandbox-thinking" completed={false} showCompletionIcon={false} />
}
