import clsx from 'clsx'

import { TraceNodeKind } from '../types'
import { NODE_KIND_COLORS } from './nodeKindColors'

const KIND_LABELS: Record<TraceNodeKind, { letter: string; label: string }> = {
    trace: { letter: 'T', label: 'Trace' },
    span: { letter: 'S', label: 'Span' },
    generation: { letter: 'G', label: 'Generation' },
    embedding: { letter: 'E', label: 'Embedding' },
}

export interface NodeKindGlyphProps {
    kind: TraceNodeKind
    size?: 'small' | 'medium'
}

export function NodeKindGlyph({ kind, size = 'small' }: NodeKindGlyphProps): JSX.Element {
    const { letter, label } = KIND_LABELS[kind]
    return (
        <span
            role="img"
            aria-label={label}
            title={label}
            // Not `cn`: its tailwind-merge does not know the custom `text-xxs` size, reads it as a text
            // color, and drops `text-white`, which leaves dark letters on the fill in the light theme.
            className={clsx(
                'inline-flex shrink-0 items-center justify-center rounded font-semibold text-white',
                NODE_KIND_COLORS[kind].glyphBg,
                size === 'small' ? 'size-4 text-xxs' : 'size-5 text-xs'
            )}
        >
            {letter}
        </span>
    )
}
