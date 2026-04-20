import type { JSONContent } from '@tiptap/core'

/**
 * The @react-email/editor stores documents as TipTap JSONContent, which always has
 * `type: 'doc'` at the root. We use this marker to distinguish new designs from
 * legacy Unlayer designs (which have `body`/`counters`/`schemaVersion`).
 */
export type ReactEmailDesign = JSONContent & { type: 'doc' }

/**
 * Shape of the merge tags passed into the new editor — intentionally the same
 * subset of Unlayer's merge tag shape that we already populate in the logic, so
 * both editors can share one selector.
 */
export type ReactEmailMergeTag = {
    name: string
    value: string
    sample?: string
}

export type ReactEmailMergeTags = Record<string, ReactEmailMergeTag>

export function isReactEmailDesign(design: unknown): design is ReactEmailDesign {
    return (
        !!design &&
        typeof design === 'object' &&
        (design as { type?: string }).type === 'doc' &&
        Array.isArray((design as { content?: unknown }).content)
    )
}

export function isUnlayerDesign(design: unknown): boolean {
    if (!design || typeof design !== 'object') {
        return false
    }
    const d = design as Record<string, unknown>
    return 'body' in d && 'counters' in d && 'schemaVersion' in d
}
