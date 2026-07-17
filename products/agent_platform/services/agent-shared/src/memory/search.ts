/**
 * Memory search — MiniSearch BM25 over memory file contents.
 *
 * Two-pass:
 *   1. List the agent's files, Range-GET each one's frontmatter (~4KB).
 *      Build a fresh MiniSearch index over headers, run the cue, take top-K.
 *   2. Full-GET the top-K to score the body and pick a snippet around the
 *      first matched term.
 *
 * No persistent index — every search rebuilds. Per the design (slice, no
 * worker-shared cache), correctness beats throughput for v0. The off-the-shelf
 * BM25 implementation handles field weighting, IDF, normalization, and
 * stopwords for us; the hand-rolled version is gone for a reason.
 */

import MiniSearch from 'minisearch'

import { MemoryFile, MemoryHeader, MemoryScope, MemoryStore } from './store'

export interface SearchResult {
    path: string
    description: string
    tags: string[]
    score: number
    snippet?: string
}

export interface SearchOpts {
    /** Optional path prefix to scope the search (e.g. "incidents/"). */
    prefix?: string
    /** Max results returned to the caller. Capped at 100. */
    limit?: number
}

interface IndexedDoc {
    id: string
    path: string
    description: string
    tags: string
    body: string
}

const SNIPPET_HALF_WIDTH = 60

export async function searchMemory(
    store: MemoryStore,
    scope: MemoryScope,
    cue: string,
    opts: SearchOpts = {}
): Promise<SearchResult[]> {
    const limit = Math.max(1, Math.min(opts.limit ?? 10, 100))

    const headers = await store.list(scope, { prefix: opts.prefix })
    if (headers.length === 0) {
        return []
    }

    // Pass 1 — index headers (no body), find candidates. We separately fetch
    // bodies for the survivors below.
    const headerIndex = newIndex()
    headerIndex.addAll(
        headers.map(
            (h): IndexedDoc => ({
                id: h.path,
                path: h.path,
                description: h.frontmatter.description,
                tags: h.frontmatter.tags.join(' '),
                body: '',
            })
        )
    )
    const headerHits = headerIndex.search(cue, {
        boost: { description: 4, tags: 3, path: 2 },
        prefix: true,
        fuzzy: 0.2,
    })

    // No header hits at all? Still fetch bodies for the first `limit` headers
    // and score by body alone — supports cues that only match body text. We
    // don't fetch every file though; cap at `limit` to bound the cost.
    const candidatePaths =
        headerHits.length > 0
            ? headerHits.slice(0, limit).map((h) => String(h.id))
            : headers.slice(0, limit).map((h) => h.path)

    const files = await Promise.all(
        candidatePaths.map(async (path) => {
            const headerMatch = headers.find((h) => h.path === path)!
            const file = await store.read(scope, path)
            return { headerMatch, file }
        })
    )

    // Pass 2 — final index including body. The boost mirrors §3 weights:
    // description >> tags >> path >> body.
    const fullIndex = newIndex()
    fullIndex.addAll(
        files.map(
            ({ file }): IndexedDoc => ({
                id: file.path,
                path: file.path,
                description: file.frontmatter.description,
                tags: file.frontmatter.tags.join(' '),
                body: file.content,
            })
        )
    )
    const finalHits = fullIndex.search(cue, {
        boost: { description: 4, tags: 3, path: 2, body: 1 },
        prefix: true,
        fuzzy: 0.2,
    })

    return finalHits.slice(0, limit).map((hit): SearchResult => {
        const path = String(hit.id)
        const { file } = files.find((f) => f.file.path === path)!
        return {
            path,
            description: file.frontmatter.description,
            tags: file.frontmatter.tags,
            score: Math.round(hit.score * 1000) / 1000,
            snippet: pickSnippet(file.content, Object.keys(hit.match)),
        }
    })
}

function newIndex(): MiniSearch<IndexedDoc> {
    return new MiniSearch<IndexedDoc>({
        fields: ['description', 'tags', 'path', 'body'],
        storeFields: ['path', 'description', 'tags'],
        idField: 'id',
    })
}

function pickSnippet(body: string, matchedTerms: string[]): string | undefined {
    if (!body || matchedTerms.length === 0) {
        return undefined
    }
    const lower = body.toLowerCase()
    let earliest = -1
    for (const term of matchedTerms) {
        const idx = lower.indexOf(term.toLowerCase())
        if (idx >= 0 && (earliest === -1 || idx < earliest)) {
            earliest = idx
        }
    }
    if (earliest === -1) {
        return undefined
    }
    const start = Math.max(0, earliest - SNIPPET_HALF_WIDTH)
    const end = Math.min(body.length, earliest + SNIPPET_HALF_WIDTH)
    const prefix = start > 0 ? '…' : ''
    const suffix = end < body.length ? '…' : ''
    return prefix + body.slice(start, end).replace(/\s+/g, ' ').trim() + suffix
}

/** Re-export for tools.ts. */
export type { MemoryFile, MemoryHeader }
