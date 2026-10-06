import type { RepositoryFileApi } from 'products/business_knowledge/frontend/generated/api.schemas'
import type { CodeFileApi } from 'products/today/frontend/generated/api.schemas'

const CODE_SPAN = /`([^`\n]{3,80})`/g

export function codeIdentifiers(content: string): string[] {
    const spans = [...content.matchAll(CODE_SPAN)].map((match) => match[1].trim())
    return [...new Set(spans.filter((span) => !/\//.test(span) && !/^[\w-]+\.[a-z]{1,5}$/i.test(span)))]
}

export interface TodayCodeWindow {
    startLine: number
    lines: string[]
    marks: { line: number; start: number; end: number }[]
}

const EXCERPT_CONTEXT_LINES = 2
const EXCERPT_WINDOW_LINES = 5
const MAX_EXCERPT_CANDIDATES = 5
const CANDIDATE_SLACK = 2
const IMPORT_LINE = /^\s*(import\b|from\s+\S+\s+import\b|export\s+\{.*\}\s+from\b)/

interface ScoredAnchor {
    anchor: number
    found: number
    score: number
}

function scoredAnchors(fileLines: string[], content: string, identifiers: string[]): ScoredAnchor[] {
    const weight = new Map(
        identifiers.map((identifier) => [identifier, 1 / Math.max(1, content.split(identifier).length - 1)])
    )
    const anchors: ScoredAnchor[] = []
    fileLines.forEach((line, index) => {
        if (IMPORT_LINE.test(line) || !identifiers.some((identifier) => line.includes(identifier))) {
            return
        }
        const window = fileLines
            .slice(Math.max(0, index - EXCERPT_CONTEXT_LINES), index + EXCERPT_WINDOW_LINES + 1)
            .join('\n')
        const found = identifiers.filter((identifier) => window.includes(identifier))
        const rarity = found.reduce((total, identifier) => total + (weight.get(identifier) ?? 0), 0)
        anchors.push({ anchor: index, found: found.length, score: found.length + rarity / (identifiers.length + 1) })
    })
    return anchors.sort((first, second) => second.score - first.score || first.anchor - second.anchor)
}

function excerptAt(fileLines: string[], identifiers: string[], anchor: number): TodayCodeWindow {
    let start = Math.max(0, anchor - EXCERPT_CONTEXT_LINES)
    let end = Math.min(fileLines.length - 1, anchor + EXCERPT_WINDOW_LINES)
    while (start < anchor && !fileLines[start].trim()) {
        start++
    }
    while (end > anchor && !fileLines[end].trim()) {
        end--
    }
    const window = fileLines.slice(start, end + 1)
    const indent = Math.min(
        ...window.filter((line) => line.trim()).map((line) => line.length - line.trimStart().length)
    )
    const lines = window.map((line) => line.slice(indent))
    const marks = lines.flatMap((line, index) =>
        identifiers.flatMap((identifier) => {
            const found: { line: number; start: number; end: number }[] = []
            let at = line.indexOf(identifier)
            while (at >= 0) {
                found.push({ line: index, start: at, end: at + identifier.length })
                at = line.indexOf(identifier, at + identifier.length)
            }
            return found
        })
    )
    marks.sort((first, second) => first.line - second.line || first.start - second.start)
    return { startLine: start + 1, lines, marks }
}

export function codeExcerptCandidates(
    content: string,
    identifiers: string[],
    limit: number = MAX_EXCERPT_CANDIDATES
): TodayCodeWindow[] {
    if (!identifiers.length) {
        return []
    }
    const fileLines = content.split('\n')
    const anchors = scoredAnchors(fileLines, content, identifiers)
    const mostFound = anchors[0]?.found ?? 0
    const excerpts: TodayCodeWindow[] = []
    for (const { anchor, found } of anchors) {
        if (excerpts.length >= limit || found < Math.max(1, mostFound - CANDIDATE_SLACK)) {
            break
        }
        const excerpt = excerptAt(fileLines, identifiers, anchor)
        const last = excerpt.startLine + excerpt.lines.length - 1
        const overlaps = excerpts.some(
            (taken) => excerpt.startLine <= taken.startLine + taken.lines.length - 1 && last >= taken.startLine
        )
        if (!overlaps) {
            excerpts.push(excerpt)
        }
    }
    return excerpts
}

export interface TodayCodeQuote {
    file: CodeFileApi
    read: RepositoryFileApi
    excerpt: TodayCodeWindow
}

function distinctMarked(excerpt: TodayCodeWindow): number {
    return new Set(excerpt.marks.map((mark) => excerpt.lines[mark.line].slice(mark.start, mark.end))).size
}

export function findCodeQuote(
    files: CodeFileApi[],
    reads: (RepositoryFileApi | null)[],
    identifiers: string[]
): TodayCodeQuote | null {
    let best: TodayCodeQuote | null = null
    for (const [index, file] of files.entries()) {
        const read = reads[index]
        const candidates = read ? codeExcerptCandidates(read.content, identifiers) : []
        const excerpt = candidates[0]
        const marksMore = !best || (excerpt && distinctMarked(excerpt) > distinctMarked(best.excerpt))
        if (read && excerpt && marksMore) {
            best = { file, read, excerpt }
        }
    }
    return best
}
