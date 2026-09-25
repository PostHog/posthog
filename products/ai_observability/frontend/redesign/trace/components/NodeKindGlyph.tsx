import { cn } from 'lib/utils/css-classes'

import { TraceNodeKind } from '../types'

const KIND_GLYPHS: Record<TraceNodeKind, { letter: string; label: string; className: string }> = {
    trace: { letter: 'T', label: 'Trace', className: 'bg-[var(--data-color-1)]' },
    span: { letter: 'S', label: 'Span', className: 'bg-[var(--data-color-8)]' },
    generation: { letter: 'G', label: 'Generation', className: 'bg-[var(--data-color-14)]' },
    embedding: { letter: 'E', label: 'Embedding', className: 'bg-[var(--data-color-11)]' },
}

export interface NodeKindGlyphProps {
    kind: TraceNodeKind
    size?: 'small' | 'medium'
}

export function NodeKindGlyph({ kind, size = 'small' }: NodeKindGlyphProps): JSX.Element {
    const glyph = KIND_GLYPHS[kind]
    return (
        <span
            role="img"
            aria-label={glyph.label}
            title={glyph.label}
            className={cn(
                'inline-flex shrink-0 items-center justify-center rounded font-semibold text-white',
                glyph.className,
                size === 'small' ? 'size-4 text-xxs' : 'size-5 text-xs'
            )}
        >
            {glyph.letter}
        </span>
    )
}
