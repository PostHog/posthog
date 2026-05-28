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

import { EyeIcon, EyeOffIcon, XIcon } from 'lucide-react'
import type { ChatContext } from '../context'
import { describeContext } from '../context'

interface DockHeaderProps {
    context: ChatContext
    followingEnabled?: boolean
    onFollowingChange?: (next: boolean) => void
    onExitPlayground?: () => void
    onNewSession?: () => void
}

export function DockHeader({
    context,
    followingEnabled,
    onFollowingChange,
    onExitPlayground,
}: DockHeaderProps): React.ReactElement {
    const { mode, subject } = describeContext(context)
    const isPlayground = context.mode === 'playground'

    return (
        <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
            <div className="flex items-center gap-2">
                <span
                    className={
                        isPlayground
                            ? 'inline-flex h-1.5 w-1.5 rounded-full bg-warning'
                            : 'inline-flex h-1.5 w-1.5 rounded-full bg-success'
                    }
                    aria-hidden
                />
                <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{mode}</span>
            </div>
            <span className="min-w-0 flex-1 truncate text-sm text-foreground" title={subject}>
                {subject}
            </span>

            {/* Focus toggle — only meaningful in concierge mode (in playground
                the dock is talking *to* the agent, not navigating the console). */}
            {!isPlayground && onFollowingChange ? (
                <FocusToggle enabled={followingEnabled ?? true} onChange={onFollowingChange} />
            ) : null}

            {isPlayground ? (
                <button
                    type="button"
                    onClick={() => onExitPlayground?.()}
                    className="inline-flex h-6 cursor-pointer items-center gap-1 rounded-md px-1.5 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                    aria-label="Exit playground"
                >
                    <XIcon className="h-3 w-3" />
                    Exit
                </button>
            ) : null}
        </div>
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
