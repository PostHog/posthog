/**
 * Top-of-dock header. Console-specific chrome that mounts above the
 * presentation-agnostic `<AgentChat />` via its `headerSlot` prop —
 * mode pill, focus toggle, open-session button, settings menu,
 * playground exit, etc. The chat lib owns the conversation; this
 * file owns the console's framing around it.
 *
 * The header stays the same size across modes — only its content and
 * accent treatment changes — so the dock doesn't shift around as the
 * user enters / exits playground or toggles focus mode.
 */

'use client'

import {
    ChevronsRightIcon,
    ExternalLinkIcon,
    EyeIcon,
    EyeOffIcon,
    HistoryIcon,
    PanelRightIcon,
    PictureInPictureIcon,
    RotateCcwIcon,
    SettingsIcon,
    XIcon,
} from 'lucide-react'

import type { ChatContext } from '@posthog/agent-chat'
import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import type { DockMode } from '@/lib/useDockLayout'

import type { SessionHistoryEntry } from './useRealRunner'

interface DockHeaderProps {
    context: ChatContext
    followingEnabled?: boolean
    onFollowingChange?: (next: boolean) => void
    onExitPlayground?: () => void
    /**
     * Concierge-mode reset. Clears the current chat back to the waiting
     * state so the user can start a fresh conversation without
     * navigating away. Playground uses `onExitPlayground` instead.
     */
    onNewSession?: () => void
    /** True while a script is mid-playback — disables the reset button. */
    busy?: boolean
    /**
     * Non-zero when the SSE stream is reconnecting after a transient
     * drop. Renders a quiet pill so the user knows the pause is the
     * client retrying, not a stall.
     */
    reconnectAttempt?: number
    /** Current value of the "render assistant text as markdown" setting. */
    renderMarkdown?: boolean
    /** Called when the user toggles the markdown setting in the gear menu. */
    onRenderMarkdownChange?: (next: boolean) => void
    /**
     * Id of the live session. When set together with `onOpenSession` the
     * header renders a small "open in session view" button that the
     * host wires to its router. Omit (or pass undefined) before the
     * first /run lands.
     */
    sessionId?: string
    /** Called when the user clicks the open-session button. */
    onOpenSession?: (sessionId: string) => void
    /** Current dock layout mode — toggles between fixed right rail and a floating panel. */
    dockMode?: DockMode
    /** Called when the user picks a new dock layout mode from the header. */
    onChangeDockMode?: (next: DockMode) => void
    /**
     * Optional dock-hide control. When provided, the header renders a
     * small "hide dock" button. The shortcut hint surfaces in the
     * tooltip so the user discovers `⌘.` / `Ctrl+.`.
     */
    onHideDock?: () => void
    /** Display string for the hide shortcut (e.g. `⌘.` or `Ctrl+.`). */
    hideShortcutHint?: string
    /**
     * Recent sessions this browser has started with the active agent.
     * When non-empty the header renders a history dropdown so the user
     * can pick a previous conversation. Entries with `terminal: true`
     * route through `onOpenSession` (read-only playback); the rest
     * route through `onResumeSession` (live in-dock chat).
     *
     * Implicit principal scoping: this list is browser-local and only
     * accumulates sessions the viewer started, so it sidesteps the
     * "is this session mine?" question that the server-side sessions
     * tab can't sidestep.
     */
    sessionHistory?: SessionHistoryEntry[]
    /**
     * Called when the user picks a non-terminal entry. The host wires
     * this to `runner.switchToSession(id)`, which closes the current
     * SSE and re-attaches to the picked session.
     */
    onResumeSession?: (id: string) => void
}

export function DockHeader({
    context,
    followingEnabled,
    onFollowingChange,
    onExitPlayground,
    onNewSession,
    busy,
    reconnectAttempt,
    renderMarkdown,
    onRenderMarkdownChange,
    sessionId,
    onOpenSession,
    dockMode,
    onChangeDockMode,
    onHideDock,
    hideShortcutHint,
    sessionHistory,
    onResumeSession,
}: DockHeaderProps): React.ReactElement {
    const isPlayground = context.mode === 'playground'
    const playgroundAgent = context.mode === 'playground' ? context.agent.name : null
    const previewRevisionId = context.mode === 'playground' ? context.previewRevisionId : undefined
    const sessionLabel = sessionLabelFor(sessionId, sessionHistory)

    // Playground mode gets a strongly-tinted bar so it's impossible to
    // confuse "talking *to* the agent" with the ambient concierge chat.
    // Horizontal padding lives on each row (not the container) so the
    // divider between rows runs edge-to-edge instead of being inset.
    // When focus mode is on in concierge mode, the header sports a
    // primary top border to visually join up with the page-top focus
    // indicator stripe (both bg-primary) — same colour, same signal.
    const focusJoinClass = !isPlayground && followingEnabled ? 'border-t border-primary' : ''
    const containerClass = isPlayground
        ? 'flex flex-col border-b-2 border-primary bg-primary/10'
        : `flex flex-col border-b border-border ${focusJoinClass}`
    const rowDividerClass = isPlayground ? 'border-b border-primary/30' : 'border-b border-border/60'

    return (
        // `data-dock-drag-handle` lets a host frame (e.g. the floating
        // dock panel) opt into dragging the chat around by this row.
        // The host gates its mousedown handler on this attribute and
        // ignores clicks that bubble from interactive descendants.
        <div className={containerClass} data-dock-drag-handle="">
            {/* ── Row 1: mode pill (left) · config controls (right) ── */}
            <div className={'flex items-center gap-2 px-3 py-1.5 ' + rowDividerClass}>
                {/* Mode pill — same shape for both modes; colour + label tells
                    you which one you're in. Dot is animated in playground
                    (high-stakes mode) and quiet-green in concierge. */}
                {isPlayground ? (
                    <span
                        className="inline-flex items-center gap-1.5 rounded-md bg-primary px-2 py-0.5 text-[0.6875rem] font-semibold uppercase tracking-wide text-primary-foreground"
                        aria-label="Playground mode"
                    >
                        <span
                            className="inline-flex h-1.5 w-1.5 animate-pulse rounded-full bg-primary-foreground"
                            aria-hidden
                        />
                        Playground
                        {playgroundAgent ? (
                            <span className="ml-0.5 font-normal opacity-90 normal-case tracking-normal">
                                · {playgroundAgent}
                            </span>
                        ) : null}
                    </span>
                ) : (
                    <span
                        className="inline-flex items-center gap-1.5 rounded-md bg-success/15 px-2 py-0.5 text-[0.6875rem] font-semibold uppercase tracking-wide text-success-foreground"
                        aria-label="Concierge mode"
                    >
                        <span className="inline-flex h-1.5 w-1.5 rounded-full bg-success-foreground" aria-hidden />
                        Concierge
                    </span>
                )}
                {previewRevisionId ? (
                    <span
                        className="inline-flex shrink-0 items-center gap-1 rounded-md border border-warning-foreground/40 bg-warning/40 px-1.5 py-0.5 text-[0.625rem] font-medium uppercase tracking-wide text-warning-foreground"
                        title={`Talking to draft revision ${previewRevisionId} via the preview proxy.`}
                    >
                        Draft
                        <code className="font-mono normal-case opacity-70">{shortRevisionId(previewRevisionId)}</code>
                    </span>
                ) : null}
                {reconnectAttempt && reconnectAttempt > 0 ? (
                    <span
                        className="inline-flex shrink-0 items-center gap-1 rounded-md border border-border bg-muted/60 px-1.5 py-0.5 text-[0.625rem] font-medium uppercase tracking-wide text-muted-foreground"
                        role="status"
                        title={`Reconnecting to the event stream (attempt ${reconnectAttempt}).`}
                    >
                        <span
                            className="inline-flex h-1.5 w-1.5 animate-pulse rounded-full bg-muted-foreground/70"
                            aria-hidden
                        />
                        Reconnecting…
                    </span>
                ) : null}

                <div className="ml-auto flex shrink-0 items-center gap-1">
                    {!isPlayground && onFollowingChange ? (
                        <FocusToggle enabled={followingEnabled ?? true} onChange={onFollowingChange} />
                    ) : null}
                    {onRenderMarkdownChange || onChangeDockMode || (sessionId && onOpenSession) ? (
                        <SettingsMenu
                            renderMarkdown={renderMarkdown ?? true}
                            onRenderMarkdownChange={onRenderMarkdownChange}
                            dockMode={dockMode}
                            onChangeDockMode={onChangeDockMode}
                            sessionId={sessionId}
                            onOpenSession={onOpenSession}
                        />
                    ) : null}
                    {onHideDock ? <HideDockButton onHide={onHideDock} shortcutHint={hideShortcutHint} /> : null}
                </div>
            </div>

            {/* ── Row 2: session label (left) · history + new / exit (right) ── */}
            <div className="flex items-center gap-2 px-3 py-1.5">
                <div className="min-w-0 flex-1 truncate text-xs text-muted-foreground" title={sessionLabel}>
                    {sessionLabel}
                </div>
                <div className="flex shrink-0 items-center gap-1">
                    {!isPlayground &&
                    sessionHistory &&
                    sessionHistory.length > 0 &&
                    (onResumeSession || onOpenSession) ? (
                        <SessionHistoryMenu
                            history={sessionHistory}
                            currentSessionId={sessionId}
                            onResume={onResumeSession}
                            onOpenInSessionView={onOpenSession}
                        />
                    ) : null}
                    {!isPlayground && onNewSession ? (
                        <button
                            type="button"
                            onClick={() => onNewSession()}
                            disabled={busy}
                            className="inline-flex h-6 shrink-0 cursor-pointer items-center gap-1 rounded-md border border-border bg-card px-1.5 text-[0.6875rem] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-card disabled:hover:text-muted-foreground"
                            aria-label="Start a new conversation"
                            title="Clear the chat and start a fresh conversation"
                        >
                            <RotateCcwIcon className="h-3 w-3" />
                            New
                        </button>
                    ) : null}
                    {isPlayground ? (
                        <button
                            type="button"
                            onClick={() => onExitPlayground?.()}
                            className="inline-flex h-6 shrink-0 cursor-pointer items-center gap-1 rounded-md border border-border bg-card px-1.5 text-[0.6875rem] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                            aria-label="Exit playground"
                        >
                            <XIcon className="h-3 w-3" />
                            Exit
                        </button>
                    ) : null}
                </div>
            </div>
        </div>
    )
}

/**
 * Pick the best label for the current session. First-message snippet if
 * the history has it; otherwise a relative "started Xm ago"; otherwise a
 * neutral "New conversation" placeholder so the row never collapses.
 */
function sessionLabelFor(sessionId?: string, history?: SessionHistoryEntry[]): string {
    if (!sessionId) {
        return 'New conversation'
    }
    const entry = history?.find((e) => e.id === sessionId)
    if (entry?.firstMessage) {
        return entry.firstMessage
    }
    if (entry?.lastTouchedAt) {
        return `Started ${formatRelativeTime(entry.lastTouchedAt)}`
    }
    const short = sessionId.split('-').at(-1)?.slice(0, 8) ?? sessionId.slice(0, 8)
    return `Session ${short}`
}

function shortRevisionId(id: string): string {
    return id.split('-').at(-1)?.slice(0, 8) ?? id.slice(0, 8)
}

function SettingsMenu({
    renderMarkdown,
    onRenderMarkdownChange,
    dockMode,
    onChangeDockMode,
    sessionId,
    onOpenSession,
}: {
    renderMarkdown: boolean
    onRenderMarkdownChange?: (next: boolean) => void
    dockMode?: DockMode
    onChangeDockMode?: (next: DockMode) => void
    sessionId?: string
    onOpenSession?: (sessionId: string) => void
}): React.ReactElement {
    const hasDisplay = !!onRenderMarkdownChange
    const hasLayout = !!onChangeDockMode
    const hasOpen = !!(sessionId && onOpenSession)
    const currentMode: DockMode = dockMode ?? 'rail'
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                aria-label="Dock settings"
                title="Dock settings"
                className="inline-flex h-6 cursor-pointer items-center justify-center rounded-md border border-border bg-background px-1.5 text-[0.6875rem] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
                <SettingsIcon className="h-3 w-3" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
                {hasOpen ? (
                    <DropdownMenuGroup>
                        <DropdownMenuItem onSelect={() => onOpenSession!(sessionId!)}>
                            <ExternalLinkIcon className="h-3 w-3" />
                            Open in session view
                        </DropdownMenuItem>
                    </DropdownMenuGroup>
                ) : null}
                {hasOpen && (hasLayout || hasDisplay) ? <DropdownMenuSeparator /> : null}
                {hasLayout ? (
                    <DropdownMenuGroup>
                        <DropdownMenuLabel>Layout</DropdownMenuLabel>
                        <DropdownMenuCheckboxItem
                            checked={currentMode === 'rail'}
                            onCheckedChange={() => onChangeDockMode!('rail')}
                        >
                            <PanelRightIcon className="h-3 w-3" />
                            Dock to side
                        </DropdownMenuCheckboxItem>
                        <DropdownMenuCheckboxItem
                            checked={currentMode === 'floating'}
                            onCheckedChange={() => onChangeDockMode!('floating')}
                        >
                            <PictureInPictureIcon className="h-3 w-3" />
                            Float panel
                        </DropdownMenuCheckboxItem>
                    </DropdownMenuGroup>
                ) : null}
                {hasLayout && hasDisplay ? <DropdownMenuSeparator /> : null}
                {hasDisplay ? (
                    <DropdownMenuGroup>
                        <DropdownMenuLabel>Display</DropdownMenuLabel>
                        <DropdownMenuCheckboxItem
                            checked={renderMarkdown}
                            onCheckedChange={(next) => onRenderMarkdownChange!(Boolean(next))}
                        >
                            Render markdown
                        </DropdownMenuCheckboxItem>
                    </DropdownMenuGroup>
                ) : null}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

function HideDockButton({ onHide, shortcutHint }: { onHide: () => void; shortcutHint?: string }): React.ReactElement {
    const label = shortcutHint ? `Hide dock (${shortcutHint})` : 'Hide dock'
    return (
        <button
            type="button"
            onClick={onHide}
            aria-label={label}
            title={label}
            className="inline-flex h-6 cursor-pointer items-center justify-center rounded-md border border-border bg-background px-1.5 text-[0.6875rem] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
            <ChevronsRightIcon className="h-3 w-3" />
        </button>
    )
}

/**
 * Dropdown that lists recent sessions this browser started with the
 * active agent. Entries are split into two regions: resumable (current
 * default action: `onResume`, which the host wires to
 * `runner.switchToSession`) and terminal (default action:
 * `onOpenInSessionView`, which routes to the read-only playback page).
 * The currently-active session gets a small dot and a different label
 * so the user can tell they're already in it.
 */
function SessionHistoryMenu({
    history,
    currentSessionId,
    onResume,
    onOpenInSessionView,
}: {
    history: SessionHistoryEntry[]
    currentSessionId?: string
    onResume?: (id: string) => void
    onOpenInSessionView?: (id: string) => void
}): React.ReactElement {
    const resumable = history.filter((e) => !e.terminal)
    const terminal = history.filter((e) => e.terminal)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                aria-label="Recent conversations"
                title="Recent conversations"
                className="inline-flex h-6 cursor-pointer items-center gap-1 rounded-md border border-border bg-background px-1.5 text-[0.6875rem] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
                <HistoryIcon className="h-3 w-3" />
                <span className="text-[0.6875rem]">{history.length}</span>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-72">
                {resumable.length > 0 ? (
                    <DropdownMenuGroup>
                        <DropdownMenuLabel>Resume</DropdownMenuLabel>
                        {resumable.map((entry) => (
                            <DropdownMenuItem
                                key={entry.id}
                                disabled={!onResume || entry.id === currentSessionId}
                                onSelect={() => {
                                    if (entry.id === currentSessionId || !onResume) {
                                        return
                                    }
                                    onResume(entry.id)
                                }}
                            >
                                <SessionEntryRow entry={entry} active={entry.id === currentSessionId} />
                            </DropdownMenuItem>
                        ))}
                    </DropdownMenuGroup>
                ) : null}
                {resumable.length > 0 && terminal.length > 0 ? <DropdownMenuSeparator /> : null}
                {terminal.length > 0 ? (
                    <DropdownMenuGroup>
                        <DropdownMenuLabel>Past (read-only)</DropdownMenuLabel>
                        {terminal.map((entry) => (
                            <DropdownMenuItem
                                key={entry.id}
                                disabled={!onOpenInSessionView}
                                onSelect={() => onOpenInSessionView?.(entry.id)}
                            >
                                <SessionEntryRow entry={entry} active={false} />
                            </DropdownMenuItem>
                        ))}
                    </DropdownMenuGroup>
                ) : null}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

function SessionEntryRow({ entry, active }: { entry: SessionHistoryEntry; active: boolean }): React.ReactElement {
    const label =
        entry.firstMessage?.trim() || `session ${entry.id.split('-').at(-1)?.slice(0, 8) ?? entry.id.slice(0, 8)}`
    const relative = formatRelativeTime(entry.lastTouchedAt)
    return (
        <div className="flex min-w-0 flex-1 items-center gap-2">
            {active ? (
                <span className="inline-flex h-1.5 w-1.5 shrink-0 rounded-full bg-success-foreground" aria-hidden />
            ) : null}
            <span className="min-w-0 flex-1 truncate text-xs">{label}</span>
            <span className="shrink-0 text-[0.625rem] uppercase tracking-wide text-muted-foreground">{relative}</span>
        </div>
    )
}

/**
 * Compact relative time — "now", "5m", "2h", "3d", "Mar 4". Strict
 * enough to fit the trailing column of the dropdown without wrapping;
 * we don't need the precision of a full library here.
 */
function formatRelativeTime(timestampMs: number): string {
    const now = Date.now()
    const diff = Math.max(0, now - timestampMs)
    const minutes = Math.floor(diff / 60_000)
    if (minutes < 1) {
        return 'now'
    }
    if (minutes < 60) {
        return `${minutes}m`
    }
    const hours = Math.floor(minutes / 60)
    if (hours < 24) {
        return `${hours}h`
    }
    const days = Math.floor(hours / 24)
    if (days < 7) {
        return `${days}d`
    }
    // Older than a week → fall back to a short absolute date.
    const date = new Date(timestampMs)
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function FocusToggle({
    enabled,
    onChange,
}: {
    enabled: boolean
    onChange: (next: boolean) => void
}): React.ReactElement {
    const Icon = enabled ? EyeIcon : EyeOffIcon
    return (
        <button
            type="button"
            onClick={() => onChange(!enabled)}
            aria-pressed={enabled}
            aria-label={enabled ? 'Focus mode on (click to pause)' : 'Focus mode paused (click to resume)'}
            title={
                enabled
                    ? 'Focus mode on — the dock will navigate to whatever it’s working on. Click to pause.'
                    : 'Focus mode paused — the dock will narrate but not navigate. Click to resume.'
            }
            className={
                (enabled
                    ? 'border-primary bg-primary text-primary-foreground shadow-sm'
                    : 'border-border bg-background text-muted-foreground hover:text-foreground') +
                ' inline-flex h-6 w-6 cursor-pointer items-center justify-center rounded-md border transition-colors'
            }
        >
            <Icon className="h-3 w-3" />
        </button>
    )
}
