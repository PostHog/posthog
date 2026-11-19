// Codex keeps its MCP servers in config.toml. hog edits the text in place, as the Wizard does, so the
// other servers, comments and key order survive. The scanner reads just enough TOML to tell a table
// header from a line inside a multi-line string or array, and to read the keys that headers and
// key/value pairs name.

interface Statement {
    start: number
    end: number
    kind: 'header' | 'array-header' | 'pair' | 'other'
    // For a header, the table it opens. Otherwise, the table the statement sits in.
    table: string[]
    key: string[]
}

interface ScanState {
    open: '"""' | "'''" | undefined
    depth: number
}

// Fields a replaced entry loses. Codex refuses a `url` next to the stdio fields, and the auth
// fields would send another server's credentials to PostHog, which logs in with OAuth instead.
const REPLACED_FIELDS = new Set([
    'command',
    'args',
    'env',
    'env_vars',
    'cwd',
    'bearer_token_env_var',
    'http_headers',
    'env_http_headers',
    'http_headers_helper',
])

const BARE_KEY = /[A-Za-z0-9_-]+/y

const ESCAPES: Record<string, string> = {
    b: '\b',
    t: '\t',
    n: '\n',
    f: '\f',
    r: '\r',
    e: '\x1b',
    '"': '"',
    '\\': '\\',
}

function skipBlank(line: string, from: number): number {
    let i = from
    while (line[i] === ' ' || line[i] === '\t') {
        i += 1
    }

    return i
}

function closeOf(line: string, from: number, quote: string): number | undefined {
    for (let i = from; i < line.length; i++) {
        if (quote.startsWith('"') && line[i] === '\\') {
            i += 1
            continue
        }

        if (line.startsWith(quote, i)) {
            // A multi-line string may end in one or two quotes of its own, right before the delimiter.
            let end = i + quote.length
            while (quote.length === 3 && end < i + 5 && line[end] === quote[0]) {
                end += 1
            }

            return end
        }
    }

    return undefined
}

function unescape(text: string): string {
    return text.replace(
        /\\(?:u([0-9A-Fa-f]{4})|U([0-9A-Fa-f]{8})|x([0-9A-Fa-f]{2})|(.))/g,
        (escape, u4?: string, u8?: string, x2?: string, char?: string) => {
            const hex = u4 ?? u8 ?? x2
            if (hex === undefined) {
                return (char !== undefined && ESCAPES[char]) || escape
            }

            const point = parseInt(hex, 16)
            return point <= 0x10ffff ? String.fromCodePoint(point) : escape
        }
    )
}

function readKeyPart(line: string, at: number): { value: string; next: number } | undefined {
    const quote = line[at]
    if (quote === '"' || quote === "'") {
        const next = closeOf(line, at + 1, quote)
        if (next === undefined) {
            return undefined
        }

        const raw = line.slice(at + 1, next - 1)
        return { value: quote === '"' ? unescape(raw) : raw, next }
    }

    BARE_KEY.lastIndex = at
    const bare = BARE_KEY.exec(line)
    return bare ? { value: bare[0], next: at + bare[0].length } : undefined
}

function readKey(line: string, from: number): { path: string[]; next: number } | undefined {
    const path: string[] = []
    let i = from
    for (;;) {
        const part = readKeyPart(line, skipBlank(line, i))
        if (!part) {
            return undefined
        }

        path.push(part.value)
        i = skipBlank(line, part.next)
        if (line[i] !== '.') {
            return { path, next: i }
        }

        i += 1
    }
}

function readHeader(line: string): { path: string[]; array: boolean } | undefined {
    const at = skipBlank(line, 0)
    if (line[at] !== '[') {
        return undefined
    }

    const array = line[at + 1] === '['
    const key = readKey(line, at + (array ? 2 : 1))
    const close = array ? ']]' : ']'
    if (!key || !line.startsWith(close, key.next)) {
        return undefined
    }

    const rest = line.slice(key.next + close.length).trim()
    return rest === '' || rest.startsWith('#') ? { path: key.path, array } : undefined
}

function scanValue(line: string, from: number, state: ScanState): void {
    let i = from
    while (i < line.length) {
        if (state.open) {
            const close = closeOf(line, i, state.open)
            if (close === undefined) {
                return
            }

            state.open = undefined
            i = close
            continue
        }

        const char = line[i]
        if (char === '#') {
            return
        }

        if (line.startsWith('"""', i) || line.startsWith("'''", i)) {
            state.open = char === '"' ? '"""' : "'''"
            i += 3
        } else if (char === '"' || char === "'") {
            i = closeOf(line, i + 1, char) ?? line.length
        } else {
            state.depth += char === '[' || char === '{' ? 1 : char === ']' || char === '}' ? -1 : 0
            i += 1
        }
    }
}

function statements(text: string): Statement[] {
    const result: Statement[] = []
    const state: ScanState = { open: undefined, depth: 0 }
    let table: string[] = []

    for (let start = 0; start < text.length; ) {
        const newline = text.indexOf('\n', start)
        const end = newline === -1 ? text.length : newline + 1
        const line = text.slice(start, newline === -1 ? text.length : newline)
        const last = result.at(-1)

        if (last && (state.open || state.depth > 0)) {
            scanValue(line, 0, state)
            last.end = end
        } else {
            state.depth = 0
            const header = readHeader(line)
            const key = header ? undefined : readKey(line, 0)

            if (header) {
                table = header.path
                result.push({ start, end, kind: header.array ? 'array-header' : 'header', table, key: [] })
            } else if (key && line[key.next] === '=') {
                result.push({ start, end, kind: 'pair', table, key: key.path })
                scanValue(line, key.next + 1, state)
            } else {
                result.push({ start, end, kind: 'other', table, key: [] })
            }
        }

        start = end
    }

    return result
}

function startsWith(path: readonly string[], prefix: readonly string[]): boolean {
    return prefix.every((part, i) => path[i] === part)
}

function sameKey(a: readonly string[], b: readonly string[]): boolean {
    return a.length === b.length && startsWith(a, b)
}

function fullKey(statement: Statement): string[] {
    return [...statement.table, ...statement.key]
}

// The strings in a value, in order. hog doesn't unescape multi-line strings, so one counts as an
// empty string: it never reads as PostHog's URL, and the strings after it keep their places.
function stringsIn(value: string): string[] {
    const strings: string[] = []
    let i = 0
    while (i < value.length) {
        const char = value[i]
        if (char === '#') {
            const newline = value.indexOf('\n', i)
            i = newline === -1 ? value.length : newline + 1
        } else if (value.startsWith('"""', i) || value.startsWith("'''", i)) {
            const close = closeOf(value, i + 3, value.slice(i, i + 3))
            if (close === undefined) {
                break
            }

            strings.push('')
            i = close
        } else if (char === '"' || char === "'") {
            const part = readKeyPart(value, i)
            if (!part) {
                break
            }

            strings.push(part.value)
            i = part.next
        } else {
            i += 1
        }
    }

    return strings
}

export interface CodexServer {
    url?: string
    command?: string
    args: string[]
    fields: string[]
}

export function codexServer(text: string, name: string): CodexServer | undefined {
    const server = ['mcp_servers', name]
    const all = statements(text)
    if (!all.some((statement) => startsWith(fullKey(statement), server))) {
        return undefined
    }

    const fields = new Set(
        all.flatMap((statement) => {
            const key = statement.kind === 'pair' ? fullKey(statement) : statement.table
            return startsWith(key, server) && key.length > server.length ? [key[server.length] ?? ''] : []
        })
    )

    const value = (key: string): string => {
        const pair = all.find((statement) => statement.kind === 'pair' && sameKey(fullKey(statement), [...server, key]))
        const source = pair ? text.slice(pair.start, pair.end) : ''
        return source.slice((readKey(source, 0)?.next ?? source.length) + 1).trimStart()
    }

    const scalar = (key: string): string | undefined => {
        const found = value(key)
        return found.startsWith('"') || found.startsWith("'") ? stringsIn(found)[0] : undefined
    }

    const args = value('args')
    return {
        url: scalar('url'),
        command: scalar('command'),
        args: args.startsWith('[') ? stringsIn(args) : [],
        fields: [...fields],
    }
}

/**
 * The config with the server's table pointing at `url`. Undefined when the file writes `mcp_servers`
 * or the server inline or with dotted keys, because TOML can't add a table to either.
 */
export function withCodexServer(text: string, name: string, fields: Record<string, string>): string | undefined {
    const server = ['mcp_servers', name]
    const all = statements(text)

    const inline = all.some((statement) => {
        const key = fullKey(statement)
        return (
            statement.kind === 'pair' &&
            !startsWith(statement.table, server) &&
            (startsWith(server, key) || startsWith(key, server))
        )
    })
    if (inline) {
        return undefined
    }

    const pieces: string[] = []
    const missing = new Map(Object.entries(fields))
    let inServer = false
    let dropping = false
    let headerAt: number | undefined

    for (const statement of all) {
        const piece = text.slice(statement.start, statement.end)

        if (statement.kind === 'header' || statement.kind === 'array-header') {
            inServer = statement.kind === 'header' && sameKey(statement.table, server)
            dropping = startsWith(statement.table, server) && REPLACED_FIELDS.has(statement.table[2] ?? '')
        }

        if (dropping || (inServer && statement.kind === 'pair' && REPLACED_FIELDS.has(statement.key[0] ?? ''))) {
            continue
        }

        const field = inServer && statement.kind === 'pair' && statement.key.length === 1 ? statement.key[0] : undefined
        const value = field === undefined ? undefined : missing.get(field)
        if (field !== undefined && value !== undefined) {
            pieces.push(`${field} = ${value}${piece.endsWith('\n') ? '\n' : ''}`)
            missing.delete(field)
            continue
        }

        pieces.push(piece)
        if (inServer && statement.kind === 'header') {
            headerAt = pieces.length
        }
    }

    const added = [...missing].map(([field, value]) => `${field} = ${value}\n`)
    if (headerAt !== undefined) {
        const header = pieces[headerAt - 1] ?? ''
        pieces.splice(headerAt, 0, ...(header.endsWith('\n') ? added : ['\n', ...added]))
        return pieces.join('')
    }

    const contents = pieces.join('')
    const gap = contents === '' || contents.endsWith('\n\n') ? '' : '\n'
    const pad = contents === '' || contents.endsWith('\n') ? '' : '\n'
    return `${contents}${pad}${gap}[mcp_servers.${name}]\n${added.join('')}`
}
