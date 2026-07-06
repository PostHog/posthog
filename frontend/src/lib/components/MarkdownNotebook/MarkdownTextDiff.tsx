import { getTextChanges } from './textChanges'

export interface MarkdownTextDiffProps {
    before: string
    after: string
}

/**
 * Inline word/character-level diff between two strings: unchanged text is rendered plain,
 * deleted spans as <del> and inserted spans as <ins>. Generic on purpose so it can also
 * back AI suggestion previews and other before/after text displays.
 */
export function MarkdownTextDiff({ before, after }: MarkdownTextDiffProps): JSX.Element {
    const changes = getTextChanges(before, after)
    const segments: JSX.Element[] = []
    let cursor = 0

    changes.forEach((change, index) => {
        if (change.start > cursor) {
            segments.push(<span key={`unchanged-${index}`}>{before.slice(cursor, change.start)}</span>)
        }
        if (change.end > change.start) {
            segments.push(
                <del key={`deleted-${index}`} className="text-danger bg-danger-highlight line-through">
                    {before.slice(change.start, change.end)}
                </del>
            )
        }
        if (change.text) {
            segments.push(
                <ins key={`inserted-${index}`} className="text-success bg-success-highlight no-underline">
                    {change.text}
                </ins>
            )
        }
        cursor = change.end
    })

    if (cursor < before.length) {
        segments.push(<span key="unchanged-tail">{before.slice(cursor)}</span>)
    }

    return <span className="whitespace-pre-wrap">{segments}</span>
}
