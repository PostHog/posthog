import './ToolbarAIMenu.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef, useState } from 'react'

import {
    IconAI,
    IconArrowRight,
    IconBrain,
    IconCheckCircle,
    IconChevronRight,
    IconCursorClick,
    IconStopFilled,
    IconWarning,
    IconWrench,
    IconX,
} from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'

import {
    AssistantMessage,
    AssistantMessageType,
    FailureMessage,
    HumanMessage,
    PlanningMessage,
    PlanningStep,
    PlanningStepStatus,
    ReasoningMessage,
} from '~/queries/schema/schema-assistant-messages'
import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'

import { EnhancedToolCall, SelectedElementContext, ToolCallStatus, ViewItem, toolbarAILogic } from './toolbarAILogic'
import { ToolbarMarkdown, preloadMarkdown } from './ToolbarMarkdown'

const SIDEBAR_WIDTH = 380
const SIDEBAR_TRANSITION_MS = 200

function selectedElementLabel(selected: SelectedElementContext): string {
    if (selected.selector) {
        return selected.selector
    }
    if (selected.attributes.id) {
        return `${selected.tagName}#${selected.attributes.id}`
    }
    if (selected.attributes.class) {
        const firstClass = selected.attributes.class.split(/\s+/).filter(Boolean)[0]
        if (firstClass) {
            return `${selected.tagName}.${firstClass}`
        }
    }
    return selected.tagName
}

function humanizeToolName(name: string): string {
    // Humanize common tool names to match the main app's phrasing ("Executed SQL",
    // "Read data schema", etc). Fall back to a title-cased version of the raw name.
    const named: Record<string, string> = {
        execute_sql: 'Executed SQL',
        run_query: 'Ran query',
        search_insights: 'Searched insights',
        search_dashboards: 'Searched dashboards',
        search_events: 'Searched events',
        read_data_schema: 'Read data schema',
        read_data_warehouse_schema: 'Read warehouse schema',
        create_insight: 'Created insight',
        update_insight: 'Updated insight',
        todo_write: 'Planning',
        search_error_tracking_issues: 'Searched error tracking',
        analyze_user_interviews: 'Analyzed user interviews',
    }
    if (named[name]) {
        return named[name]
    }
    const spaced = name.replace(/[_-]+/g, ' ')
    return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

/**
 * Generic expandable action row — shared layout for reasoning (Thought), planning,
 * and tool calls. Mirrors the main app's `AssistantActionComponent`.
 */
function ActionRow({
    icon,
    label,
    status,
    subtitle,
    expandable,
    children,
    defaultExpanded,
}: {
    icon: React.ReactNode
    label: React.ReactNode
    status: ToolCallStatus | 'pending'
    /** Inline suffix shown next to the label (e.g. step count). */
    subtitle?: React.ReactNode
    /** Whether an expand chevron should be shown (only when there's something to reveal). */
    expandable: boolean
    children?: React.ReactNode
    defaultExpanded?: boolean
}): JSX.Element {
    const completed = status === 'completed'
    const failed = status === 'failed'
    const inProgress = status === 'in_progress'
    const [expanded, setExpanded] = useState(defaultExpanded ?? (expandable && !(completed || failed)))
    const prevInProgressRef = useRef(inProgress)
    useEffect(() => {
        // Auto-collapse once a row finishes, like the main app.
        if (prevInProgressRef.current && !inProgress && expandable) {
            setExpanded(false)
        }
        prevInProgressRef.current = inProgress
    }, [inProgress, expandable])

    return (
        <div className={clsx('ToolbarAIMenu__action', expanded && 'ToolbarAIMenu__action--expanded')}>
            <button
                type="button"
                className="ToolbarAIMenu__action-header"
                onClick={() => expandable && setExpanded((v) => !v)}
                disabled={!expandable}
            >
                <span className="ToolbarAIMenu__action-icon">{icon}</span>
                <span className="ToolbarAIMenu__action-label">{label}</span>
                {subtitle ? <span className="ToolbarAIMenu__action-subtitle">{subtitle}</span> : null}
                {inProgress ? <Spinner className="ToolbarAIMenu__action-spinner" /> : null}
                {completed ? <IconCheckCircle className="ToolbarAIMenu__action-check text-success" /> : null}
                {failed ? <IconX className="ToolbarAIMenu__action-check text-danger" /> : null}
                {expandable ? (
                    <IconChevronRight
                        className={clsx(
                            'ToolbarAIMenu__action-chevron',
                            expanded && 'ToolbarAIMenu__action-chevron--open'
                        )}
                    />
                ) : null}
            </button>
            {expanded && children ? <div className="ToolbarAIMenu__action-body">{children}</div> : null}
        </div>
    )
}

function HumanBubble({ item }: { item: HumanMessage & { status: string } }): JSX.Element {
    return (
        <div className="ToolbarAIMenu__bubble ToolbarAIMenu__bubble--human">
            <div className="ToolbarAIMenu__bubble-content">{item.content}</div>
        </div>
    )
}

function AssistantBubble({
    item,
    enhancedToolCalls,
    isStreaming,
}: {
    item: AssistantMessage & { status: string }
    enhancedToolCalls: EnhancedToolCall[] | undefined
    isStreaming: boolean
}): JSX.Element {
    const hasContent = !!item.content
    return (
        <div className="ToolbarAIMenu__bubble ToolbarAIMenu__bubble--assistant">
            {/* Text first, then tool calls — mirrors the main app so the visible
                order stays stable as tool_calls stream in below already-rendered text. */}
            {hasContent ? (
                <div className="ToolbarAIMenu__bubble-content">
                    <ToolbarMarkdown content={item.content} id={item.id ?? 'streaming'} />
                    {isStreaming ? <span className="ToolbarAIMenu__caret" aria-hidden="true" /> : null}
                </div>
            ) : null}
            {enhancedToolCalls?.length ? (
                <div className="ToolbarAIMenu__tool-calls">
                    {enhancedToolCalls.map((tc) => (
                        <ToolCallRow key={tc.id} toolCall={tc} />
                    ))}
                </div>
            ) : null}
        </div>
    )
}

function ToolCallRow({ toolCall }: { toolCall: EnhancedToolCall }): JSX.Element {
    const resultContent = toolCall.result?.content
    const hasArgs = toolCall.args && Object.keys(toolCall.args).length > 0
    const expandable = !!resultContent || hasArgs
    return (
        <ActionRow
            icon={<IconWrench />}
            label={humanizeToolName(toolCall.name)}
            status={toolCall.status}
            expandable={expandable}
            defaultExpanded={false}
        >
            {hasArgs ? (
                <>
                    <div className="ToolbarAIMenu__action-label-mini">Arguments</div>
                    <pre className="ToolbarAIMenu__code">{safeStringify(toolCall.args)}</pre>
                </>
            ) : null}
            {resultContent ? (
                <>
                    <div className="ToolbarAIMenu__action-label-mini">Result</div>
                    <pre className="ToolbarAIMenu__code">{truncate(resultContent, 2000)}</pre>
                </>
            ) : null}
        </ActionRow>
    )
}

function ReasoningRow({ item }: { item: ReasoningMessage & { status: string } }): JSX.Element {
    const isCompleted = item.status === 'completed'
    const label = isCompleted ? 'Thought' : 'Thinking…'
    const body = item.content
    return (
        <ActionRow
            icon={<IconBrain />}
            label={label}
            status={isCompleted ? 'completed' : 'in_progress'}
            expandable={!!body}
        >
            {body ? <ToolbarMarkdown content={body} id={item.id ?? 'reasoning'} /> : null}
        </ActionRow>
    )
}

function PlanningRow({ item }: { item: PlanningMessage & { status: string } }): JSX.Element {
    const steps = item.steps ?? []
    const total = steps.length
    const done = steps.filter((s) => s.status === PlanningStepStatus.Completed).length
    const anyInProgress = steps.some((s) => s.status === PlanningStepStatus.InProgress)
    const allDone = total > 0 && done === total
    const planStatus: ToolCallStatus = allDone ? 'completed' : anyInProgress ? 'in_progress' : 'pending'
    return (
        <ActionRow
            icon={<IconBrain />}
            label="Planning"
            subtitle={total > 0 ? `(${done}/${total})` : null}
            status={planStatus === 'pending' ? 'in_progress' : planStatus}
            expandable={total > 0}
        >
            <ul className="ToolbarAIMenu__plan">
                {steps.map((step: PlanningStep, idx) => (
                    <li key={idx} className={`ToolbarAIMenu__plan-step ToolbarAIMenu__plan-step--${step.status}`}>
                        <span className="ToolbarAIMenu__plan-step-marker" aria-hidden="true">
                            {step.status === PlanningStepStatus.Completed
                                ? '✓'
                                : step.status === PlanningStepStatus.InProgress
                                  ? '●'
                                  : '○'}
                        </span>
                        <span className="ToolbarAIMenu__plan-step-text">{step.description}</span>
                    </li>
                ))}
            </ul>
        </ActionRow>
    )
}

function FailureRow({ item }: { item: FailureMessage & { status: string } }): JSX.Element {
    return (
        <div className="ToolbarAIMenu__failure">
            <IconWarning />
            <span>{item.content || 'Something went wrong.'}</span>
        </div>
    )
}

function ThreadItemView({
    item,
    isLastAssistant,
    isStreaming,
}: {
    item: ViewItem
    isLastAssistant: boolean
    isStreaming: boolean
}): JSX.Element | null {
    switch (item.type) {
        case AssistantMessageType.Human:
            return <HumanBubble item={item} />
        case AssistantMessageType.Assistant:
            return (
                <AssistantBubble
                    item={item}
                    enhancedToolCalls={item.enhancedToolCalls}
                    isStreaming={isLastAssistant && isStreaming}
                />
            )
        case AssistantMessageType.Reasoning:
            return <ReasoningRow item={item} />
        case AssistantMessageType.Planning:
            return <PlanningRow item={item} />
        case AssistantMessageType.Failure:
            return <FailureRow item={item} />
        default:
            return null
    }
}

function safeStringify(value: unknown): string {
    try {
        return JSON.stringify(value, null, 2)
    } catch {
        return String(value)
    }
}

function truncate(s: string, max: number): string {
    return s.length > max ? s.slice(0, max) + '…' : s
}

export function ToolbarAIMenu(): JSX.Element {
    const { thread, viewItems, isStreaming, isCapturingContext, isBusy, error, pickMode, selectedElementContext } =
        useValues(toolbarAILogic)
    const { submitMessage, cancelStream, reset, startElementPick, cancelElementPick, clearSelectedElementContext } =
        useActions(toolbarAILogic)
    const { setVisibleMenu } = useActions(toolbarLogic)

    const [draft, setDraft] = useState('')
    const scrollRef = useRef<HTMLDivElement | null>(null)
    const inputRef = useRef<HTMLTextAreaElement | null>(null)

    const lastAssistantIndex = useMemo(() => {
        for (let i = viewItems.length - 1; i >= 0; i--) {
            if (viewItems[i].type === AssistantMessageType.Assistant) {
                return i
            }
        }
        return -1
    }, [viewItems])

    // Show an explicit "Thinking…" placeholder whenever the stream is in flight
    // but nothing is actively streaming yet. Covers the dead time between submit
    // and the first server event (workflow startup, LLM cold-start, etc.) and
    // between tool-call completion and the next assistant turn.
    const showThinkingPlaceholder = useMemo(() => {
        if (!isStreaming) {
            return false
        }
        const lastItem = viewItems[viewItems.length - 1]
        if (!lastItem) {
            return true
        }
        // If the last item is still loading / in-progress, the row itself
        // already shows a spinner — don't double it up.
        if (lastItem.status === 'loading') {
            return false
        }
        if (lastItem.type === AssistantMessageType.Assistant && lastItem.enhancedToolCalls?.length) {
            const anyInProgress = lastItem.enhancedToolCalls.some((tc) => tc.status === 'in_progress')
            if (anyInProgress) {
                return false
            }
        }
        // A completed human turn or a completed assistant/tool row means we're
        // waiting for the next message — show the placeholder.
        return true
    }, [isStreaming, viewItems])

    // Push page content to the left so the sidebar doesn't cover it — mirrors
    // the Product Tours sidebar. Restored on unmount.
    useEffect(() => {
        const prevTransition = document.body.style.transition
        const prevMarginRight = document.body.style.marginRight
        document.body.style.transition = `margin ${SIDEBAR_TRANSITION_MS}ms ease-out`
        document.body.style.marginRight = `${SIDEBAR_WIDTH}px`
        // Warm up the markdown renderer chunk so the first streamed reply can
        // render rich markdown without waiting for the network round-trip.
        preloadMarkdown()
        return () => {
            document.body.style.transition = prevTransition
            document.body.style.marginRight = prevMarginRight
        }
    }, [])

    // Auto-scroll to bottom when new content arrives.
    useEffect(() => {
        const el = scrollRef.current
        if (el) {
            el.scrollTop = el.scrollHeight
        }
    }, [viewItems, isCapturingContext])

    // Refocus the input after a turn completes so users can type the next question
    // without clicking back into the textarea.
    useEffect(() => {
        if (!isBusy) {
            inputRef.current?.focus()
        }
    }, [isBusy])

    const onSubmit = (): void => {
        if (!draft.trim() || isBusy) {
            return
        }
        submitMessage(draft)
        setDraft('')
    }

    const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>): void => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            onSubmit()
        }
    }

    return (
        <div
            className="ToolbarAIMenu"
            onClick={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ width: SIDEBAR_WIDTH }}
        >
            <header className="ToolbarAIMenu__header">
                <div className="flex items-center gap-1.5 font-semibold">
                    <IconAI className="text-lg" />
                    <span>PostHog AI</span>
                </div>
                <div className="flex items-center gap-1">
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        onClick={reset}
                        disabledReason={isBusy ? 'Wait for the current response to finish' : undefined}
                    >
                        New chat
                    </LemonButton>
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        icon={<IconX />}
                        tooltip="Close"
                        onClick={() => setVisibleMenu('none')}
                    />
                </div>
            </header>

            <div ref={scrollRef} className="ToolbarAIMenu__scroll">
                {viewItems.length === 0 ? (
                    <div className="ToolbarAIMenu__empty">
                        <IconAI className="text-3xl mb-2" />
                        <div className="font-semibold">Ask PostHog AI about this page</div>
                        <div className="text-xs ToolbarAIMenu__muted mt-1">
                            PostHog AI can see your page and your PostHog data. Try: "Why is the signup button click
                            rate dropping?"
                        </div>
                    </div>
                ) : (
                    viewItems.map((item, idx) => (
                        <ThreadItemView
                            key={item.id || `item-${idx}`}
                            item={item}
                            isLastAssistant={idx === lastAssistantIndex}
                            isStreaming={isStreaming}
                        />
                    ))
                )}
                {isCapturingContext ? (
                    <div className="ToolbarAIMenu__status">
                        <Spinner /> Capturing page context…
                    </div>
                ) : null}
                {showThinkingPlaceholder ? (
                    <div className="ToolbarAIMenu__status">
                        <Spinner /> Thinking…
                    </div>
                ) : null}
                {error ? (
                    <div className="ToolbarAIMenu__status text-danger">
                        <IconWarning /> {error}
                    </div>
                ) : null}
            </div>

            <footer className="ToolbarAIMenu__footer">
                {pickMode ? (
                    <div className="ToolbarAIMenu__pick-banner">
                        <span>
                            <IconCursorClick /> Click an element on the page to attach it…
                        </span>
                        <LemonButton size="xsmall" type="tertiary" onClick={cancelElementPick}>
                            Cancel
                        </LemonButton>
                    </div>
                ) : null}

                <label className="ToolbarAIMenu__input-box" htmlFor="toolbar-ai-input">
                    <div className="ToolbarAIMenu__input-body">
                        {!draft ? (
                            <div className="ToolbarAIMenu__input-placeholder" aria-hidden="true">
                                {thread.length === 0 ? 'Ask a question' : 'Ask follow-up'}{' '}
                                <span className="ToolbarAIMenu__input-placeholder-hint">or / for commands</span>
                            </div>
                        ) : null}
                        <textarea
                            ref={inputRef}
                            id="toolbar-ai-input"
                            className="ToolbarAIMenu__input"
                            value={draft}
                            onChange={(e) => setDraft(e.target.value)}
                            onKeyDown={onKeyDown}
                            rows={1}
                            disabled={isBusy}
                        />
                    </div>

                    <div className="ToolbarAIMenu__input-actions">
                        <button
                            type="button"
                            className={clsx(
                                'ToolbarAIMenu__context-pill',
                                pickMode && 'ToolbarAIMenu__context-pill--active'
                            )}
                            onClick={pickMode ? cancelElementPick : startElementPick}
                            disabled={isBusy}
                            title={
                                pickMode
                                    ? 'Cancel element pick'
                                    : selectedElementContext
                                      ? 'Pick a different element'
                                      : 'Pick an element from the page'
                            }
                        >
                            <IconCursorClick />
                            <span>{pickMode ? 'Picking…' : 'Element'}</span>
                        </button>

                        {selectedElementContext ? (
                            <div
                                className="ToolbarAIMenu__context-pill ToolbarAIMenu__context-pill--filled"
                                title={selectedElementContext.textPreview}
                            >
                                <span className="ToolbarAIMenu__context-pill-label">
                                    {selectedElementLabel(selectedElementContext)}
                                </span>
                                <button
                                    type="button"
                                    className="ToolbarAIMenu__context-pill-clear"
                                    onClick={clearSelectedElementContext}
                                    aria-label="Remove selected element"
                                >
                                    <IconX />
                                </button>
                            </div>
                        ) : null}
                    </div>

                    <div className="ToolbarAIMenu__send-wrap">
                        {isStreaming ? (
                            <LemonButton
                                size="small"
                                type="secondary"
                                icon={<IconStopFilled />}
                                onClick={cancelStream}
                                tooltip="Stop generation"
                            />
                        ) : (
                            <LemonButton
                                size="small"
                                type={draft.trim() ? 'primary' : 'secondary'}
                                icon={<IconArrowRight />}
                                onClick={onSubmit}
                                disabledReason={
                                    isBusy
                                        ? 'Wait for PostHog AI to finish'
                                        : !draft.trim()
                                          ? 'Type a message'
                                          : undefined
                                }
                            />
                        )}
                    </div>
                </label>
            </footer>
        </div>
    )
}
