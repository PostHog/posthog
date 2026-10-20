import { TraceNodeKind } from '../types'

export interface NodeKindColorClasses {
    glyphBg: string
    barBg: string
    barBorder: string
}

// Tailwind needs literal class strings, so every kind's classes are spelled out here rather
// than built from the data-color number at runtime.
export const NODE_KIND_COLORS: Record<TraceNodeKind, NodeKindColorClasses> = {
    trace: {
        glyphBg: 'bg-[var(--data-color-1)]',
        barBg: 'bg-[var(--data-color-1)]/20',
        barBorder: 'border-[var(--data-color-1)]/60',
    },
    span: {
        glyphBg: 'bg-[var(--data-color-8)]',
        barBg: 'bg-[var(--data-color-8)]/20',
        barBorder: 'border-[var(--data-color-8)]/60',
    },
    generation: {
        glyphBg: 'bg-[var(--data-color-14)]',
        barBg: 'bg-[var(--data-color-14)]/25',
        barBorder: 'border-[var(--data-color-14)]/60',
    },
    embedding: {
        glyphBg: 'bg-[var(--data-color-11)]',
        barBg: 'bg-[var(--data-color-11)]/25',
        barBorder: 'border-[var(--data-color-11)]/60',
    },
}
