/**
 * Memory file format — YAML frontmatter (the "what this is") + markdown body
 * (the "what it says"). Hand-rolled parser because the schema is tiny and fixed,
 * and pulling a full YAML lib into the runner for four keys is overkill.
 *
 * Shape:
 *   ---
 *   description: One-line summary, <= 280 chars.
 *   tags: [tag1, tag2]
 *   created_at: 2026-02-14T03:22:10Z
 *   updated_at: 2026-02-14T11:08:45Z
 *   ---
 *
 *   # Body markdown — anything goes
 *
 * Only the first leading `---...---` block is treated as frontmatter; nested
 * `---` separators inside the body are preserved verbatim.
 */

export interface MemoryFrontmatter {
    description: string
    tags: string[]
    createdAt?: string
    updatedAt?: string
}

export interface MemoryDoc extends MemoryFrontmatter {
    content: string
}

export const MAX_DESCRIPTION_LEN = 280

/**
 * Parse a full memory file. Frontmatter is optional — a body with no `---`
 * fence parses to `{ description: '', tags: [], content: <raw> }`.
 */
export function parseMemoryDoc(raw: string): MemoryDoc {
    const fm = extractFrontmatter(raw)
    if (!fm) {
        return { description: '', tags: [], content: raw }
    }
    return { ...parseFrontmatterBlock(fm.block), content: fm.body }
}

/**
 * Parse only the frontmatter, ignoring the body. Used by ranking pass that
 * Range-GETs the first ~2KB of each candidate file — we never have the full
 * body, just enough to read the front block.
 */
export function parseMemoryFrontmatter(raw: string): MemoryFrontmatter {
    const fm = extractFrontmatter(raw)
    if (!fm) {
        return { description: '', tags: [] }
    }
    return parseFrontmatterBlock(fm.block)
}

/**
 * Serialize a doc back to disk format. Timestamps are stamped here so callers
 * don't have to remember; pass `createdAt` to preserve it on update.
 */
export function serializeMemoryDoc(doc: {
    description: string
    tags?: string[]
    content: string
    createdAt?: string
    updatedAt?: string
}): string {
    const lines: string[] = ['---']
    lines.push(`description: ${escapeYamlString(doc.description)}`)
    lines.push(`tags: ${serializeTags(doc.tags ?? [])}`)
    if (doc.createdAt) {
        lines.push(`created_at: ${doc.createdAt}`)
    }
    if (doc.updatedAt) {
        lines.push(`updated_at: ${doc.updatedAt}`)
    }
    lines.push('---', '', doc.content.replace(/\s+$/, ''), '')
    return lines.join('\n')
}

/** Throws if the input violates the write-time invariants. */
export function validateForWrite(input: { description: string; tags?: string[] }): void {
    if (input.description.length === 0) {
        throw new Error('description is required')
    }
    if (input.description.length > MAX_DESCRIPTION_LEN) {
        throw new Error(`description exceeds ${MAX_DESCRIPTION_LEN} chars (got ${input.description.length})`)
    }
    if (input.description.includes('\n')) {
        throw new Error('description must be a single line')
    }
    for (const tag of input.tags ?? []) {
        if (!/^[a-z0-9_-]+$/.test(tag)) {
            throw new Error(`invalid tag "${tag}" — lowercase ascii a-z 0-9 _ - only`)
        }
    }
}

function extractFrontmatter(raw: string): { block: string; body: string } | null {
    if (!raw.startsWith('---')) {
        return null
    }
    const lines = raw.split('\n')
    if (lines[0].trim() !== '---') {
        return null
    }
    let end = -1
    for (let i = 1; i < lines.length; i++) {
        if (lines[i].trim() === '---') {
            end = i
            break
        }
    }
    if (end === -1) {
        return null
    }
    return {
        block: lines.slice(1, end).join('\n'),
        // Strip the leading blank line the serializer adds, and the trailing
        // newline the serializer pads with so parse is symmetric with
        // serialize for content the caller passed in verbatim.
        body: lines
            .slice(end + 1)
            .join('\n')
            .replace(/^\n+/, '')
            .replace(/\n+$/, ''),
    }
}

function parseFrontmatterBlock(block: string): MemoryFrontmatter {
    const out: MemoryFrontmatter = { description: '', tags: [] }
    for (const line of block.split('\n')) {
        const m = line.match(/^([a-z_]+):\s*(.*)$/)
        if (!m) {
            continue
        }
        const [, key, rawVal] = m
        const val = rawVal.trim()
        if (key === 'description') {
            out.description = unescapeYamlString(val)
        } else if (key === 'tags') {
            out.tags = parseTags(val)
        } else if (key === 'created_at') {
            out.createdAt = val
        } else if (key === 'updated_at') {
            out.updatedAt = val
        }
    }
    return out
}

function escapeYamlString(s: string): string {
    // Single-line, descriptions don't have multi-line tricks. Quote only if
    // the string would confuse a naive YAML parser (leading whitespace,
    // colon, quote, `#`, `[`/`{`/`>` markers, or starts with `-`).
    if (/^[^\s:#"'[{>-][^\n]*$/.test(s) && !s.includes('  ')) {
        return s
    }
    return `"${s.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`
}

function unescapeYamlString(s: string): string {
    if (s.startsWith('"') && s.endsWith('"') && s.length >= 2) {
        return s.slice(1, -1).replace(/\\"/g, '"').replace(/\\\\/g, '\\')
    }
    if (s.startsWith("'") && s.endsWith("'") && s.length >= 2) {
        return s.slice(1, -1).replace(/''/g, "'")
    }
    return s
}

function parseTags(raw: string): string[] {
    if (!raw.startsWith('[') || !raw.endsWith(']')) {
        return []
    }
    return raw
        .slice(1, -1)
        .split(',')
        .map((t) => t.trim())
        .filter((t) => t.length > 0)
}

function serializeTags(tags: string[]): string {
    return `[${tags.join(', ')}]`
}
