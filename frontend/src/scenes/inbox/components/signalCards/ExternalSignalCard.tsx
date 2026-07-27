import clsx from 'clsx'

import { IconExternal } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import type { SignalNode } from 'scenes/debug/signals/types'

import { SignalCardShell } from './SignalCardShell'

export type StatePillTone = 'success' | 'danger' | 'warning' | 'muted' | 'default'

const STATE_PILL_TONE_CLASSES: Record<StatePillTone, string> = {
    success: 'bg-success-highlight text-success',
    danger: 'bg-danger-highlight text-danger',
    warning: 'bg-warning-highlight text-warning',
    muted: 'bg-fill-highlight-50 text-muted',
    default: 'bg-fill-highlight-50 text-secondary',
}

export interface StatePill {
    label: string
    tone: StatePillTone
}

/** Small pill with a leading status dot, e.g. an issue's open/closed state. */
export function StatePillBadge({ pill }: { pill: StatePill }): JSX.Element {
    return (
        <span
            className={clsx(
                'inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-xs font-medium',
                STATE_PILL_TONE_CLASSES[pill.tone]
            )}
        >
            <span className="size-1.5 rounded-full bg-current" />
            {pill.label}
        </span>
    )
}

/**
 * Presentational shell for external-source signal cards (GitHub, Linear, Zendesk, pganalyze).
 * Captures the common anatomy — brand-icon header, optional state pill + title, markdown body,
 * a chip meta row, and a footer with timestamps on the left and a prominent external link on the
 * right. Product-specific colourings (label chips, priority indicators) are passed in via `metaChips`.
 */
export function ExternalSignalCard({
    signal,
    title,
    statePill,
    children,
    metaChips,
    footerLeft,
    link,
}: {
    signal: SignalNode
    /** Optional title shown in the header (e.g. issue number or identifier). */
    title?: React.ReactNode
    /** Optional state pill rendered in the header right slot. */
    statePill?: StatePill
    /** Body content — typically the signal description. If a string, rendered as markdown. */
    children?: React.ReactNode
    /** Chip row (labels, tags, priority, status). Caller-rendered for product-specific colours. */
    metaChips?: React.ReactNode
    /** Footer left content, typically timestamps. */
    footerLeft?: React.ReactNode
    /** Primary external link-out. Always opens in a new tab. */
    link?: { to: string; label: string }
}): JSX.Element {
    return (
        <SignalCardShell
            signal={signal}
            label={title}
            rightSlot={statePill ? <StatePillBadge pill={statePill} /> : undefined}
        >
            {typeof children === 'string' ? (
                <LemonMarkdown className="text-sm text-secondary mb-2" disableImages>
                    {children}
                </LemonMarkdown>
            ) : (
                children
            )}

            {metaChips && <div className="flex items-center gap-1.5 flex-wrap">{metaChips}</div>}

            {(footerLeft || link) && (
                <div className="flex items-center gap-2 flex-wrap text-xs text-tertiary mt-2">
                    {footerLeft}
                    <span className="flex-1" />
                    {link && (
                        <Link
                            to={link.to}
                            target="_blank"
                            className="flex items-center gap-1 text-xs font-medium shrink-0"
                        >
                            {link.label} <IconExternal className="size-3" />
                        </Link>
                    )}
                </div>
            )}
        </SignalCardShell>
    )
}
