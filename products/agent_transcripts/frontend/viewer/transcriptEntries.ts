export type TranscriptEntryKind = 'message' | 'user' | 'thinking' | 'tool' | 'web' | 'system'

export interface TranscriptEntry {
    id: string
    /** The line or message the entry came from, shown in the gutter. */
    sequence: number
    kind: TranscriptEntryKind
    title: string
    text: string
    output?: string
    exitCode?: number
    status?: 'running' | 'passed' | 'failed'
}

export type JsonRecord = Record<string, unknown>

export const record = (value: unknown): JsonRecord =>
    typeof value === 'object' && value !== null && !Array.isArray(value) ? (value as JsonRecord) : {}

export const string = (value: unknown): string => (typeof value === 'string' ? value : '')

/** Text from a string or from an array of `{ text }` blocks, the two shapes providers use for content. */
export const blocksText = (value: unknown): string =>
    typeof value === 'string'
        ? value
        : Array.isArray(value)
          ? value
                .map((part) => string(record(part).text) || string(part))
                .filter(Boolean)
                .join('\n')
          : ''

function commandText(command: unknown): string {
    if (!Array.isArray(command)) {
        return string(command)
    }
    const parts = command.map(String)
    // Codex wraps shell commands as ["bash", "-lc", "<script>"].
    return parts.length === 3 && parts[1] === '-lc' ? parts[2] : parts.join(' ')
}

/** The argument that says what a tool call did, such as its command, path or query. */
export function toolText(value: unknown): string {
    const args = record(value)
    const summary =
        commandText(args.command ?? args.cmd) ||
        string(args.filePath ?? args.file_path ?? args.path ?? args.url ?? args.query ?? args.pattern)

    return summary || (Object.keys(args).length ? JSON.stringify(args) : '')
}

export const toolKind = (name: string): TranscriptEntryKind => (/web|fetch|search/i.test(name) ? 'web' : 'tool')

export function parseJson(text: string): unknown {
    try {
        return JSON.parse(text)
    } catch {
        return undefined
    }
}
