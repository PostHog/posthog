/**
 * Span-replacement primitives over plain strings: diff (LCS), apply, invert, and
 * operational transform. These are the coordinate-mapping layer the editor uses for
 * merging concurrent edits and rebasing undo history over remote changes.
 */

/** A replaced span: offsets in UTF-16 code units, matching the backend's diff format. */
export type TextChange = {
    start: number
    end: number
    text: string
}

const MAX_EXACT_TEXT_DIFF_CELLS = 4_000_000

/** Minimal-ish span changes transforming baseText → nextText (ascending, non-overlapping). */
export function getTextChanges(baseText: string, nextText: string): TextChange[] {
    if (baseText === nextText) {
        return []
    }

    if (baseText.length * nextText.length > MAX_EXACT_TEXT_DIFF_CELLS) {
        return getSingleSpanTextChange(baseText, nextText)
    }

    const width = nextText.length + 1
    const lcsLengths = new Uint16Array((baseText.length + 1) * width)

    for (let baseIndex = baseText.length - 1; baseIndex >= 0; baseIndex--) {
        for (let nextIndex = nextText.length - 1; nextIndex >= 0; nextIndex--) {
            const offset = baseIndex * width + nextIndex
            lcsLengths[offset] =
                baseText[baseIndex] === nextText[nextIndex]
                    ? lcsLengths[(baseIndex + 1) * width + nextIndex + 1] + 1
                    : Math.max(lcsLengths[(baseIndex + 1) * width + nextIndex], lcsLengths[offset + 1])
        }
    }

    const changes: TextChange[] = []
    let activeChange: TextChange | null = null
    let baseIndex = 0
    let nextIndex = 0

    const ensureActiveChange = (): TextChange => {
        if (!activeChange) {
            activeChange = { start: baseIndex, end: baseIndex, text: '' }
        }
        return activeChange
    }
    const flushActiveChange = (): void => {
        if (activeChange) {
            changes.push(activeChange)
            activeChange = null
        }
    }

    while (baseIndex < baseText.length || nextIndex < nextText.length) {
        if (baseIndex < baseText.length && nextIndex < nextText.length && baseText[baseIndex] === nextText[nextIndex]) {
            flushActiveChange()
            baseIndex += 1
            nextIndex += 1
            continue
        }

        if (
            nextIndex < nextText.length &&
            (baseIndex === baseText.length ||
                lcsLengths[baseIndex * width + nextIndex + 1] >= lcsLengths[(baseIndex + 1) * width + nextIndex])
        ) {
            ensureActiveChange().text += nextText[nextIndex]
            nextIndex += 1
            continue
        }

        ensureActiveChange().end += 1
        baseIndex += 1
    }

    flushActiveChange()
    return changes
}

function getSingleSpanTextChange(baseText: string, nextText: string): TextChange[] {
    let prefixLength = 0
    while (
        prefixLength < baseText.length &&
        prefixLength < nextText.length &&
        baseText[prefixLength] === nextText[prefixLength]
    ) {
        prefixLength += 1
    }

    let suffixLength = 0
    while (
        suffixLength < baseText.length - prefixLength &&
        suffixLength < nextText.length - prefixLength &&
        baseText[baseText.length - suffixLength - 1] === nextText[nextText.length - suffixLength - 1]
    ) {
        suffixLength += 1
    }

    return [
        {
            start: prefixLength,
            end: baseText.length - suffixLength,
            text: nextText.slice(prefixLength, nextText.length - suffixLength),
        },
    ]
}

/** Apply trusted changes (ascending, non-overlapping) produced by this module. */
export function applyTextChanges(baseText: string, changes: TextChange[]): string {
    let nextText = ''
    let cursor = 0
    changes.forEach((change) => {
        nextText += baseText.slice(cursor, change.start)
        nextText += change.text
        cursor = change.end
    })
    return nextText + baseText.slice(cursor)
}

/**
 * Apply untrusted text changes (ascending, non-overlapping) to a base string.
 * Returns null when the changes don't fit the base — the caller should fall
 * back to a full reload. Mirrors `apply_utf16_text_changes` in the backend.
 */
export function tryApplyTextChanges(baseText: string, changes: TextChange[]): string | null {
    let nextText = ''
    let cursor = 0
    for (const change of changes) {
        if (
            typeof change?.start !== 'number' ||
            typeof change?.end !== 'number' ||
            typeof change?.text !== 'string' ||
            !Number.isInteger(change.start) ||
            !Number.isInteger(change.end) ||
            change.start < cursor ||
            change.start > change.end ||
            change.end > baseText.length
        ) {
            return null
        }
        nextText += baseText.slice(cursor, change.start)
        nextText += change.text
        cursor = change.end
    }
    return nextText + baseText.slice(cursor)
}

/** Changes that revert `changes`, with offsets relative to the post-change text. */
export function invertTextChanges(baseText: string, changes: TextChange[]): TextChange[] {
    const inverted: TextChange[] = []
    let delta = 0
    for (const change of changes) {
        const start = change.start + delta
        inverted.push({
            start,
            end: start + change.text.length,
            text: baseText.slice(change.start, change.end),
        })
        delta += change.text.length - (change.end - change.start)
    }
    return inverted
}

export type TextChangeTiePriority = 'against-first' | 'changes-first'

/**
 * Map a base-text position through `against` (ascending, non-overlapping).
 * `right` bias lands after insertions at the same point and after the replacement
 * text of a span containing the position; `left` bias lands before both.
 */
export function mapTextIndex(index: number, against: TextChange[], bias: 'left' | 'right'): number {
    let delta = 0
    for (const change of against) {
        if (change.start > index) {
            break
        }
        if (change.start === index) {
            if (bias === 'right' && change.start === change.end) {
                delta += change.text.length
                continue
            }
            break
        }
        if (index < change.end) {
            return change.start + delta + (bias === 'right' ? change.text.length : 0)
        }
        delta += change.text.length - (change.end - change.start)
    }
    return index + delta
}

/**
 * Rebase `changes` so they apply to `applyTextChanges(base, against)` instead of the base.
 * Both inputs are relative to the same base text.
 *
 * Convergence policy (the ProseMirror-rebase trade): insertions always survive, and a
 * deletion never swallows text the other side inserted — the deleted range splits around
 * the other side's insertions. `priority` breaks ties for insertions at the same point.
 * When both sides deleted overlapping ranges there is no coherent character-level merge
 * (interleaving two rewrites of the same word produces garbage), so that case returns
 * null and the caller resolves it as a genuine conflict.
 */
export function transformTextChanges(
    changes: TextChange[],
    against: TextChange[],
    priority: TextChangeTiePriority = 'against-first'
): TextChange[] | null {
    const insertionBias = priority === 'against-first' ? 'right' : 'left'
    const transformed: TextChange[] = []

    for (const change of changes) {
        if (change.start === change.end) {
            // Insertions at the same point with a shared prefix are continued typing seen
            // twice (an autosave echo): only the unseen suffix is added, never a duplicate.
            let text = change.text
            const tie = against.find((other) => other.start === change.start && other.start === other.end)
            if (tie?.text && text) {
                if (tie.text.startsWith(text)) {
                    text = ''
                } else if (text.startsWith(tie.text)) {
                    text = text.slice(tie.text.length)
                }
            }
            if (text) {
                const position = mapTextIndex(change.start, against, text === change.text ? insertionBias : 'right')
                transformed.push({ start: position, end: position, text })
            }
            continue
        }

        if (against.some((other) => other.start < other.end && other.start < change.end && other.end > change.start)) {
            return null
        }

        // Split the deleted range around the other side's insertions, so their text survives.
        const survivingSegments: { start: number; end: number }[] = []
        let cursor = change.start
        for (const other of against) {
            if (other.start >= change.end) {
                break
            }
            if (other.end <= cursor) {
                continue
            }
            if (other.start > cursor) {
                survivingSegments.push({ start: cursor, end: Math.min(other.start, change.end) })
            }
            cursor = Math.max(cursor, other.end)
        }
        if (cursor < change.end) {
            survivingSegments.push({ start: cursor, end: change.end })
        }

        survivingSegments.forEach((segment, segmentIndex) => {
            const start = mapTextIndex(segment.start, against, 'right')
            const end = Math.max(start, mapTextIndex(segment.end, against, 'left'))
            transformed.push({ start, end, text: segmentIndex === 0 ? change.text : '' })
        })
    }

    return normalizeTransformedChanges(transformed)
}

/** Drop no-op spans and guard ordering so the output always satisfies tryApplyTextChanges. */
function normalizeTransformedChanges(changes: TextChange[]): TextChange[] {
    const normalized: TextChange[] = []
    let cursor = 0
    for (const change of changes) {
        const start = Math.max(change.start, cursor)
        const end = Math.max(change.end, start)
        if (start === end && !change.text) {
            continue
        }
        normalized.push({ start, end, text: change.text })
        cursor = end
    }
    return normalized
}
