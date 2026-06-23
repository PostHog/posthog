import { signalCardSourceLine } from 'lib/signals/signalCardSourceLine'
import type { SignalNode } from 'scenes/debug/signals/types'

import { getSourceProductMeta } from '../badges/sourceProductIcons'

/**
 * Header shared by every signal card: the source product's brand icon, the human
 * "Product · Signal type" line, and an optional label/right slot.
 */
export function SignalCardHeader({
    signal,
    label,
    rightSlot,
}: {
    signal: SignalNode
    /** Optional bold title shown after the source line (e.g. an entity name). */
    label?: React.ReactNode
    /** Optional content rendered at the end of the header (e.g. a severity badge). */
    rightSlot?: React.ReactNode
}): JSX.Element {
    const meta = getSourceProductMeta(signal.source_product)
    const Icon = meta?.Icon

    return (
        <div className="flex items-center gap-2 mb-2">
            {Icon ? (
                <span
                    className="inline-flex shrink-0 items-center"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ color: meta?.color }}
                    aria-hidden
                >
                    <Icon className="text-base" />
                </span>
            ) : (
                <span className="size-2.5 rounded-full shrink-0 bg-border" />
            )}
            <span className="text-xs font-medium text-tertiary">{signalCardSourceLine(signal)}</span>
            {label && <span className="text-xs font-medium text-primary flex-1 truncate">{label}</span>}
            <span className="flex-1" />
            {rightSlot}
        </div>
    )
}

/** Bordered card container + shared header. Per-source cards render their body as `children`. */
export function SignalCardShell({
    signal,
    label,
    rightSlot,
    children,
}: {
    signal: SignalNode
    label?: React.ReactNode
    rightSlot?: React.ReactNode
    children: React.ReactNode
}): JSX.Element {
    return (
        <div className="border rounded p-3 bg-surface-primary">
            <SignalCardHeader signal={signal} label={label} rightSlot={rightSlot} />
            {children}
        </div>
    )
}
