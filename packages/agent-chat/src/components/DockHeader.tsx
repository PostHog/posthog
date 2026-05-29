/**
 * Top-of-dock header. Minimal — a small pill indicating the mode,
 * the subject of the conversation, a focus-mode toggle so the user
 * can pause the dock's autonomous navigation, and (when in
 * playground) an exit.
 *
 * The header stays the same size across modes — only its content and
 * accent treatment changes — so the dock doesn't shift around as the
 * user enters / exits playground or toggles focus mode.
 */

import { ExternalLinkIcon, EyeIcon, EyeOffIcon, RotateCcwIcon, SettingsIcon, XIcon } from 'lucide-react'
import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuLabel,
    DropdownMenuTrigger,
} from '@posthog/quill'
import type { ChatContext } from '../context'
import { describeContext } from '../context'

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
}: DockHeaderProps): React.ReactElement {
    const { mode, subject } = describeContext(context)
    const isPlayground = context.mode === 'playground'
    const previewRevisionId = context.mode === 'playground' ? context.previewRevisionId : undefined

    // Playground mode gets a strongly-tinted bar so it's impossible to
    // confuse "talking *to* the agent" with the ambient concierge chat.
    // Uses the brand-orange primary tone (high chroma) at low opacity
    // for the surface, full-strength for the badge + accent line.
    const containerClass = isPlayground
        ? 'flex items-center gap-2 border-b-2 border-primary bg-primary/10 px-4 py-2.5'
        : 'flex items-center gap-2 border-b border-border px-4 py-2.5'

    return (
        <div className={containerClass}>
            {isPlayground ? (
                <span
                    className="inline-flex items-center gap-1 rounded-md bg-primary px-1.5 py-0.5 text-[0.625rem] font-semibold uppercase tracking-wide text-primary-foreground"
                    aria-label="Playground mode"
                >
                    <span className="inline-flex h-1.5 w-1.5 animate-pulse rounded-full bg-primary-foreground" aria-hidden />
                    Playground
                </span>
            ) : (
                <div className="flex items-center gap-2">
                    <span className="inline-flex h-1.5 w-1.5 rounded-full bg-success-foreground" aria-hidden />
                    <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{mode}</span>
                </div>
            )}
            <span
                className={
                    'min-w-0 flex-1 truncate text-sm ' +
                    (isPlayground ? 'font-medium text-foreground' : 'text-foreground')
                }
                title={previewRevisionId ? `${subject} (preview revision)` : subject}
            >
                {subject}
            </span>
            {/* Preview-revision pill: lit up when the playground is talking
             *  to a non-live revision via Django's preview-proxy rather
             *  than the public ingress URL. Skipped for the live-revision
             *  path to keep the header quieter when nothing's special. */}
            {previewRevisionId ? (
                <span
                    className="inline-flex shrink-0 items-center gap-1 rounded-md border border-warning-foreground/40 bg-warning/40 px-1.5 py-0.5 text-[0.625rem] font-medium uppercase tracking-wide text-warning-foreground"
                    title={`Talking to draft revision ${previewRevisionId} via the preview proxy.`}
                >
                    Draft
                    <code className="font-mono normal-case opacity-70">{shortRevisionId(previewRevisionId)}</code>
                </span>
            ) : null}

            {/* Reconnect pill: visible while `listen()` is retrying with
             *  backoff after a transient drop. Cleared as soon as the
             *  next SSE event arrives (handled in the runner). */}
            {reconnectAttempt && reconnectAttempt > 0 ? (
                <span
                    className="inline-flex shrink-0 items-center gap-1 rounded-md border border-border bg-muted/60 px-1.5 py-0.5 text-[0.625rem] font-medium uppercase tracking-wide text-muted-foreground"
                    role="status"
                    title={`Reconnecting to the event stream (attempt ${reconnectAttempt}).`}
                >
                    <span className="inline-flex h-1.5 w-1.5 animate-pulse rounded-full bg-muted-foreground/70" aria-hidden />
                    Reconnecting…
                </span>
            ) : null}

            {/* Focus toggle — only meaningful in concierge mode (in playground
                the dock is talking *to* the agent, not navigating the console). */}
            {!isPlayground && onFollowingChange ? (
                <FocusToggle enabled={followingEnabled ?? true} onChange={onFollowingChange} />
            ) : null}

            {sessionId && onOpenSession ? (
                <button
                    type="button"
                    onClick={() => onOpenSession(sessionId)}
                    className="inline-flex h-6 cursor-pointer items-center gap-1 rounded-md border border-border bg-background px-1.5 text-[0.6875rem] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                    aria-label="Open this session in the session view"
                    title="Open this session in the session view"
                >
                    <ExternalLinkIcon className="h-3 w-3" />
                    Session
                </button>
            ) : null}

            {onRenderMarkdownChange ? (
                <SettingsMenu
                    renderMarkdown={renderMarkdown ?? true}
                    onRenderMarkdownChange={onRenderMarkdownChange}
                />
            ) : null}

            {!isPlayground && onNewSession ? (
                <button
                    type="button"
                    onClick={() => onNewSession()}
                    disabled={busy}
                    className="inline-flex h-6 cursor-pointer items-center gap-1 rounded-md px-1.5 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-transparent disabled:hover:text-muted-foreground"
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
                    className="inline-flex h-6 cursor-pointer items-center gap-1 rounded-md px-1.5 text-xs font-medium text-foreground/80 transition-colors hover:bg-primary/20 hover:text-foreground"
                    aria-label="Exit playground"
                >
                    <XIcon className="h-3 w-3" />
                    Exit
                </button>
            ) : null}
        </div>
    )
}

function shortRevisionId(id: string): string {
    // Mirrors `short()` in the console's RevisionsBrowser — last 8 chars of
    // the trailing UUID segment. Short enough to read in the header pill,
    // unique enough to disambiguate sibling drafts at a glance.
    return id.split('-').at(-1)?.slice(0, 8) ?? id.slice(0, 8)
}

function SettingsMenu({
    renderMarkdown,
    onRenderMarkdownChange,
}: {
    renderMarkdown: boolean
    onRenderMarkdownChange: (next: boolean) => void
}): React.ReactElement {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <button
                        type="button"
                        aria-label="Chat display settings"
                        title="Display settings"
                        className="inline-flex h-6 cursor-pointer items-center justify-center rounded-md border border-border bg-background px-1.5 text-[0.6875rem] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                    >
                        <SettingsIcon className="h-3 w-3" />
                    </button>
                }
            />
            <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuGroup>
                    <DropdownMenuLabel>Display</DropdownMenuLabel>
                    <DropdownMenuCheckboxItem
                        checked={renderMarkdown}
                        onCheckedChange={(next) => onRenderMarkdownChange(Boolean(next))}
                    >
                        Render markdown
                    </DropdownMenuCheckboxItem>
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
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
            aria-label={enabled ? 'Pause focus mode' : 'Resume focus mode'}
            title={
                enabled
                    ? 'Focus mode on — the dock will navigate to whatever it’s working on. Click to pause.'
                    : 'Focus mode paused — the dock will narrate but not navigate. Click to resume.'
            }
            className={
                (enabled
                    ? 'border-info/40 bg-info/10 text-info-foreground'
                    : 'border-border bg-background text-muted-foreground hover:text-foreground') +
                ' inline-flex h-6 cursor-pointer items-center gap-1 rounded-md border px-1.5 text-[0.6875rem] font-medium transition-colors'
            }
        >
            <Icon className="h-3 w-3" />
            <span>Focus</span>
        </button>
    )
}
