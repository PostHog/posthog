import {
    NotebookBlockNode,
    NotebookComponentProps,
    NotebookDocument,
    NotebookInlineMark,
    NotebookInlineNode,
    NotebookListItem,
    NotebookPropValue,
} from './types'

const nodeFingerprintCache = new WeakMap<NotebookBlockNode, string>()

export function hashString(value: string): string {
    let hash = 5381
    for (let index = 0; index < value.length; index++) {
        hash = (hash * 33) ^ value.charCodeAt(index)
    }
    return (hash >>> 0).toString(36)
}

export function normalizeWhitespace(value: string): string {
    return value.replace(/\s+/g, ' ').trim()
}

export function createStableNodeId(fingerprint: string, occurrence: number): string {
    return `mdn-${hashString(fingerprint)}-${occurrence}`
}

export function ensureUniqueNodeIds(nodes: NotebookBlockNode[]): NotebookBlockNode[] {
    const seenIds = new Set<string>()
    let didChange = false

    const uniqueNodes = nodes.map((node, index) => {
        if (node.id && !seenIds.has(node.id)) {
            seenIds.add(node.id)
            return node
        }

        didChange = true
        let occurrence = 0
        let nextId = createStableNodeId(
            `${node.id || 'empty'}:${getNodeFingerprint(node)}:${String(index)}`,
            occurrence
        )
        while (seenIds.has(nextId)) {
            occurrence += 1
            nextId = createStableNodeId(
                `${node.id || 'empty'}:${getNodeFingerprint(node)}:${String(index)}`,
                occurrence
            )
        }

        seenIds.add(nextId)
        return { ...node, id: nextId }
    })

    return didChange ? uniqueNodes : nodes
}

export function cloneNotebookDocument(document: NotebookDocument): NotebookDocument {
    return JSON.parse(JSON.stringify(document)) as NotebookDocument
}

export function cloneNotebookNode<T extends NotebookBlockNode>(node: T): T {
    return JSON.parse(JSON.stringify(node)) as T
}

export function getInlineText(nodes: NotebookInlineNode[]): string {
    return nodes.map((node) => (node.type === 'hardBreak' ? '\n' : node.text)).join('')
}

export function getNodeText(node: NotebookBlockNode): string {
    if (node.type === 'paragraph' || node.type === 'heading' || node.type === 'blockquote') {
        return getInlineText(node.children)
    }
    if (node.type === 'list') {
        return node.items.map((item) => getInlineText(item.children)).join('\n')
    }
    if (node.type === 'table') {
        return [
            node.headers.map((cell) => getInlineText(cell.children)).join(' '),
            ...node.rows.map((row) => row.map((cell) => getInlineText(cell.children)).join(' ')),
        ].join('\n')
    }
    if (node.type === 'code') {
        return node.text
    }
    if (node.type === 'component') {
        return `${node.tagName}:${JSON.stringify(node.props)}`
    }
    return ''
}

export function getNodeSignature(node: NotebookBlockNode): string {
    if (node.type === 'heading') {
        return `${node.type}:${node.level ?? 1}`
    }
    if (node.type === 'list') {
        return `${node.type}:${node.ordered ? `ordered:${String(node.start ?? 1)}` : 'bullet'}`
    }
    if (node.type === 'table') {
        return `${node.type}:${node.headers.length}`
    }
    if (node.type === 'component') {
        return `${node.type}:${node.tagName}`
    }
    return node.type
}

export function getNodeFingerprint(node: NotebookBlockNode): string {
    const cachedFingerprint = nodeFingerprintCache.get(node)
    if (cachedFingerprint !== undefined) {
        return cachedFingerprint
    }

    const fingerprint = getUncachedNodeFingerprint(node)
    nodeFingerprintCache.set(node, fingerprint)
    return fingerprint
}

function getUncachedNodeFingerprint(node: NotebookBlockNode): string {
    if (node.type === 'paragraph' || node.type === 'heading' || node.type === 'blockquote') {
        return JSON.stringify({
            type: node.type,
            level: node.level,
            children: node.children,
        })
    }
    if (node.type === 'list') {
        return JSON.stringify({
            type: node.type,
            ordered: node.ordered,
            start: node.start,
            items: node.items.map(getListItemFingerprint),
        })
    }
    if (node.type === 'table') {
        return JSON.stringify({
            type: node.type,
            headers: node.headers,
            rows: node.rows,
            alignments: node.alignments,
        })
    }
    if (node.type === 'code') {
        return JSON.stringify({
            type: node.type,
            language: node.language,
            text: node.text,
        })
    }
    if (node.type === 'component') {
        return JSON.stringify({
            type: node.type,
            tagName: node.tagName,
            props: sortProps(node.props),
        })
    }
    return JSON.stringify(node)
}

function getListItemFingerprint(item: NotebookListItem): Omit<NotebookListItem, 'id'> {
    return {
        children: item.children,
        depth: item.depth,
        ordered: item.ordered,
        start: item.start,
        checked: item.checked,
    }
}

export function textSimilarity(left: string, right: string): number {
    const normalizedLeft = normalizeForSimilarity(left)
    const normalizedRight = normalizeForSimilarity(right)
    if (!normalizedLeft && !normalizedRight) {
        return 1
    }
    if (!normalizedLeft || !normalizedRight) {
        return 0
    }
    if (normalizedLeft.includes(normalizedRight) || normalizedRight.includes(normalizedLeft)) {
        const shorterLength = Math.min(normalizedLeft.length, normalizedRight.length)
        if (shorterLength >= 4) {
            return 0.6
        }
        return (
            Math.min(normalizedLeft.length, normalizedRight.length) /
            Math.max(normalizedLeft.length, normalizedRight.length)
        )
    }

    const leftWords = new Set(normalizedLeft.split(' '))
    const rightWords = new Set(normalizedRight.split(' '))
    const intersection = [...leftWords].filter((word) => rightWords.has(word)).length
    const union = new Set([...leftWords, ...rightWords]).size
    return union === 0 ? 0 : intersection / union
}

function normalizeForSimilarity(value: string): string {
    // Punctuation becomes a separator (not stripped), so JSON-ish content — component props
    // are serialized as one JSON blob — tokenizes into comparable words instead of one
    // giant word that any single change makes entirely dissimilar.
    return value
        .toLowerCase()
        .replace(/[^\w]+/g, ' ')
        .trim()
}

export function marksEqual(left: NotebookInlineMark[], right: NotebookInlineMark[]): boolean {
    return JSON.stringify(normalizeInlineMarks(left)) === JSON.stringify(normalizeInlineMarks(right))
}

export function normalizeInlineMarks(marks: NotebookInlineMark[]): NotebookInlineMark[] {
    const dedupedMarks: NotebookInlineMark[] = []
    const seenTypes = new Set<NotebookInlineMark['type']>()

    marks.forEach((mark) => {
        if (seenTypes.has(mark.type)) {
            return
        }
        seenTypes.add(mark.type)
        dedupedMarks.push(mark)
    })

    return dedupedMarks.sort((left, right) => getInlineMarkOrder(left) - getInlineMarkOrder(right))
}

function getInlineMarkOrder(mark: NotebookInlineMark): number {
    if (mark.type === 'code') {
        return 0
    }
    if (mark.type === 'bold') {
        return 1
    }
    if (mark.type === 'italic') {
        return 2
    }
    if (mark.type === 'underline') {
        return 3
    }
    if (mark.type === 'strike') {
        return 4
    }
    if (mark.type === 'mention') {
        return 6
    }
    if (mark.type === 'ref') {
        // Outermost, so the ref tag wraps the fully formatted text.
        return 7
    }
    return 5
}

export function normalizeInlineNodes(nodes: NotebookInlineNode[]): NotebookInlineNode[] {
    const normalized: NotebookInlineNode[] = []

    nodes.forEach((node) => {
        if (node.type === 'hardBreak') {
            if (normalized[normalized.length - 1]?.type !== 'hardBreak') {
                normalized.push(node)
            }
            return
        }

        if (!node.text) {
            return
        }

        const marks = normalizeInlineMarks(node.marks ?? [])
        const previous = normalized[normalized.length - 1]
        if (previous?.type === 'text' && marksEqual(previous.marks ?? [], marks)) {
            previous.text += node.text
            return
        }

        normalized.push({
            ...node,
            marks: marks.length ? marks : undefined,
        })
    })

    return normalized
}

export function isNotebookComponentProps(value: unknown): value is NotebookComponentProps {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        return false
    }

    return Object.values(value).every(isNotebookPropValue)
}

export function isNotebookPropValue(value: unknown): value is NotebookComponentProps[string] {
    if (value === null || typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
        return true
    }

    if (Array.isArray(value)) {
        return value.every(isNotebookPropValue)
    }

    if (typeof value === 'object') {
        return Object.values(value).every(isNotebookPropValue)
    }

    return false
}

// Project a value onto the serializable NotebookPropValue space — the same JSON.stringify
// normalization markdown serialization applies — dropping nested `undefined` (e.g. an absent
// `label`/`group_type_index` on a person-property filter inside a query). Counterpart to the
// isNotebookPropValue guard: where the guard rejects dirty values, this cleans them. Returns
// `undefined` for values JSON can't represent (top-level `undefined`, functions, symbols), so
// callers can omit the key entirely.
export function toSerializablePropValue(value: unknown): NotebookPropValue | undefined {
    const serialized = JSON.stringify(value)
    if (serialized === undefined) {
        return undefined
    }
    return JSON.parse(serialized) as NotebookPropValue
}

function sortProps(props: NotebookComponentProps): NotebookComponentProps {
    return Object.keys(props)
        .sort()
        .reduce<NotebookComponentProps>((accumulator, key) => {
            accumulator[key] = sortPropValue(props[key])
            return accumulator
        }, {})
}

function sortPropValue(value: NotebookComponentProps[string]): NotebookComponentProps[string] {
    if (Array.isArray(value)) {
        return value.map(sortPropValue)
    }
    if (value && typeof value === 'object') {
        return sortProps(value)
    }
    return value
}
