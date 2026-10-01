/**
 * Rewrite agent object tags into markdown the web app can render.
 *
 * Agents cite PostHog objects with XML-style tags
 * (`<insight id="9pQx3">checkout funnel</insight>`,
 * `<insight id="x" display="block" title="…"/>`). The desktop app renders them
 * as chips; the web markdown pipeline (`ReactMarkdown` with `skipHtml`) drops
 * raw HTML nodes, so a label-less block tag renders as nothing. This module
 * runs before markdown parsing and turns each tag into a link into the
 * current project, a fenced SQL block, or just the label.
 *
 * The kind registry is generated from `posthog/object_tags/kinds.py`, and the
 * transform mirrors the Slack renderer
 * (`products/tasks/backend/temporal/slack_relay/object_tags.py`) minus its
 * Slack-specific escaping, so a reply reads the same on both surfaces. Tags
 * inside fenced code blocks and inline code spans stay literal. A trailing
 * tag or fence that is still streaming in is held back from the rendered
 * output; it re-renders whole once the rest of the chunk arrives.
 */
import { OBJECT_KIND_ALIASES, OBJECT_KIND_DATA, ObjectKindData } from './objectKinds.generated'

// A link whose URL is longer than this degrades to its plain label; a SQL editor
// deep link carries the whole query in the query string.
const MAX_LINK_URL_LENGTH = 2000

// A streamed render that ends inside a tag would flash the fragments as raw text;
// hold back at most this much so a genuinely unterminated tag still shows eventually.
const MAX_HELD_SUFFIX = 4000

const RE_OPEN_TAG = /<([a-z][\w-]*)((?:\s+[a-z][\w-]*\s*=\s*"[^"]*")*)\s*(\/>|>)/g
const RE_CLOSE_TAG = /<\/([a-z][\w-]*)\s*>/g
const RE_ATTR = /([a-z][\w-]*)\s*=\s*"([^"]*)"/g
const RE_FENCE_LINE = /^ {0,3}(`{3,}|~{3,})/
const RE_BACKTICK_RUN = /`+/g
const RE_LABEL_UNSAFE = /[[\]|]/g
const RE_BARE_ID = /^[\w$.:-]{1,64}$/
const RE_PARTIAL_OPEN_TAG = /^<(?:[a-z][\w-]*(?:\s[^>]*)?)?$/

// Only the five entities the desktop composer's XML serializer emits (`escapeXmlAttr`);
// the full HTML entity table would rewrite SQL literals such as `'&copy;'`.
const XML_ENTITIES: Record<string, string> = {
    '&quot;': '"',
    '&apos;': "'",
    '&lt;': '<',
    '&gt;': '>',
    '&amp;': '&',
}
const RE_XML_ENTITY = /&(?:quot|apos|lt|gt|amp);/g

function unescapeXml(value: string): string {
    return value.replace(RE_XML_ENTITY, (entity) => XML_ENTITIES[entity])
}

interface Span {
    start: number
    end: number
}

interface Tag {
    name: string
    attrs: Record<string, string>
    body: string
    start: number
    end: number
}

function resolveKind(name: string): ObjectKindData | null {
    const canonical = OBJECT_KIND_ALIASES[name] ?? name
    return (OBJECT_KIND_DATA as Record<string, ObjectKindData>)[canonical] ?? null
}

function parseAttrs(raw: string): Record<string, string> {
    const attrs: Record<string, string> = {}
    for (const match of raw.matchAll(RE_ATTR)) {
        attrs[match[1]] = unescapeXml(match[2])
    }
    return attrs
}

/** CommonMark inline code on one line: a run of N backticks closes on the next run of exactly N. */
function inlineCodeSpans(line: string, offset: number): Span[] {
    const runs = Array.from(line.matchAll(RE_BACKTICK_RUN))
    const spans: Span[] = []
    let index = 0
    while (index < runs.length) {
        const opener = runs[index]
        const length = opener[0].length
        const closerIndex = runs.findIndex((run, i) => i > index && run[0].length === length)
        if (closerIndex === -1) {
            index += 1
            continue
        }
        const closer = runs[closerIndex]
        spans.push({ start: offset + opener.index, end: offset + closer.index + closer[0].length })
        index = closerIndex + 1
    }
    return spans
}

/**
 * Fenced blocks and inline code, found in one pass over the lines. Mirrors the
 * desktop renderer's fence rules: a backtick or tilde fence of three or more,
 * closed only by a run of the same character at least as long with nothing else
 * on the line, and an unclosed fence runs to the end of the text.
 */
function scanCode(text: string): Span[] {
    const spans: Span[] = []
    let fenceChar = ''
    let fenceLength = 0
    let fenceStart = 0
    let offset = 0
    for (const line of text.split('\n')) {
        const fence = RE_FENCE_LINE.exec(line)
        if (fenceChar) {
            const closes =
                fence !== null &&
                fence[1][0] === fenceChar &&
                fence[1].length >= fenceLength &&
                line.slice(fence[0].length).trim() === ''
            if (closes) {
                spans.push({ start: fenceStart, end: offset + line.length })
                fenceChar = ''
            }
        } else if (fence) {
            fenceChar = fence[1][0]
            fenceLength = fence[1].length
            fenceStart = offset
        } else {
            spans.push(...inlineCodeSpans(line, offset))
        }
        offset += line.length + 1
    }
    if (fenceChar) {
        spans.push({ start: fenceStart, end: text.length })
    }
    return spans
}

/**
 * Find complete tags in `text` in order, without overlaps. Openers that start
 * inside code spans are not tags, and a tag whose closer never arrives is not a
 * tag either: the text stays as it was.
 */
function scanTags(text: string, skipSpans: Span[]): Tag[] {
    const closers = new Map<string, RegExpExecArray[]>()
    for (const close of text.matchAll(RE_CLOSE_TAG)) {
        const list = closers.get(close[1]) ?? []
        list.push(close)
        closers.set(close[1], list)
    }
    const cursors = new Map<string, number>()
    const tags: Tag[] = []
    let nextAllowed = 0
    let spanCursor = 0
    for (const match of text.matchAll(RE_OPEN_TAG)) {
        const start = match.index
        // Openers and spans are both in text order, so the span cursor only moves forward.
        while (spanCursor < skipSpans.length && skipSpans[spanCursor].end <= start) {
            spanCursor += 1
        }
        const inCode =
            spanCursor < skipSpans.length && skipSpans[spanCursor].start <= start && start < skipSpans[spanCursor].end
        if (start < nextAllowed || inCode) {
            continue
        }
        const name = match[1]
        const attrs = parseAttrs(match[2])
        const openEnd = start + match[0].length
        if (match[3] === '/>') {
            tags.push({ name, attrs, body: '', start, end: openEnd })
            nextAllowed = openEnd
            continue
        }
        const candidates = closers.get(name) ?? []
        let cursor = cursors.get(name) ?? 0
        while (cursor < candidates.length && candidates[cursor].index < openEnd) {
            cursor += 1
        }
        cursors.set(name, cursor)
        if (cursor >= candidates.length) {
            continue
        }
        const close = candidates[cursor]
        tags.push({ name, attrs, body: text.slice(openEnd, close.index), start, end: close.index + close[0].length })
        nextAllowed = close.index + close[0].length
    }
    return tags
}

function safeLabel(label: string): string {
    // Brackets and pipes end a markdown link label early, and a raw angle bracket
    // would parse as HTML that `skipHtml` then drops. The entities render back as
    // the characters.
    const collapsed = label.replace(RE_LABEL_UNSAFE, ' ').split(/\s+/).filter(Boolean).join(' ')
    return collapsed.replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function link(label: string, url: string | null): string {
    if (url === null || url.length > MAX_LINK_URL_LENGTH) {
        return label
    }
    return `[${label}](${url})`
}

function encodeObjectId(objectId: string): string {
    // `encodeURIComponent` leaves `!'()*` bare, but an unencoded `)` ends a
    // markdown `[label](url)` link early. Encoding them also matches Python's
    // `quote(safe="")`, so the Slack renderer and this one emit identical URLs.
    return encodeURIComponent(objectId).replace(
        /[!'()*]/g,
        (char) => `%${char.charCodeAt(0).toString(16).toUpperCase()}`
    )
}

// Guard patterns are static generated data and this module runs on every render
// of every streamed message, so compile them once at module load.
const ID_GUARDS = new Map<ObjectKindData, RegExp>(
    Object.values(OBJECT_KIND_DATA).flatMap((data) =>
        data.idPattern !== null ? [[data, new RegExp(data.idPattern)] as const] : []
    )
)

function objectUrl(projectBase: string, kind: ObjectKindData, objectId: string): string | null {
    if (kind.pathTemplate === null) {
        return null
    }
    const guard = ID_GUARDS.get(kind)
    if (guard && !guard.test(objectId)) {
        return null
    }
    return projectBase + kind.pathTemplate.replace('{id}', encodeObjectId(objectId))
}

function renderHogql(tag: Tag, projectBase: string): string | null {
    // A body written by the desktop composer is XML-escaped, so `&lt;` is a `<` in the SQL.
    const sql = unescapeXml(tag.body).trim()
    if (!sql) {
        return null
    }
    const hogql = OBJECT_KIND_DATA.hogql
    const url = objectUrl(projectBase, hogql, sql)
    if (tag.attrs['display'] !== 'block') {
        const label = safeLabel(tag.attrs['label'] || tag.attrs['title'] || '') || hogql.kindLabel
        return link(label, url)
    }
    const title = safeLabel(tag.attrs['title'] || '') || hogql.kindLabel
    // A backtick run in the SQL at least as long as the fence would close it early
    // and spill the rest of the query into ordinary markdown.
    const longestRun = Math.max(0, ...Array.from(sql.matchAll(RE_BACKTICK_RUN), (run) => run[0].length))
    const fence = '`'.repeat(Math.max(3, longestRun + 1))
    const lines = [`**${link(title, url)}**`, fence, sql, fence]
    // Same treatment as every other agent-authored string here: without it the
    // caption is the one attribute that could smuggle markdown link/image syntax.
    const caption = safeLabel(tag.attrs['caption'] || '')
    if (caption) {
        lines.push(`_${caption}_`)
    }
    return lines.join('\n')
}

function renderReference(tag: Tag, kind: ObjectKindData, projectBase: string): string | null {
    let objectId = (tag.attrs['id'] || '').trim()
    let body = tag.body.trim()
    if (!objectId && RE_BARE_ID.test(body)) {
        // The older `<insight>abc123</insight>` form Max's notebook tools still write.
        objectId = body
        body = ''
    }
    if (!objectId) {
        // A tag with a title but no id (a notebook query node) has no page to link; keep the title.
        return safeLabel(tag.attrs['title'] || '') || null
    }
    const label = safeLabel(tag.attrs['title'] || body) || `${kind.kindLabel} ${safeLabel(objectId)}`
    return link(label, objectUrl(projectBase, kind, objectId))
}

function renderTag(tag: Tag, projectBase: string): string | null {
    const kind = resolveKind(tag.name)
    if (kind === null) {
        // An agent sometimes extends the convention to a kind nobody renders
        // (`<inbox id="…">`). The label is still the useful part, so keep it and
        // drop the markup — but only for tags shaped like object references.
        const label = safeLabel(tag.body)
        return 'id' in tag.attrs && label ? label : null
    }
    if (kind.idIsBody) {
        return renderHogql(tag, projectBase)
    }
    return renderReference(tag, kind, projectBase)
}

// One compiled closer pattern per kind name; only registered kinds reach the
// lookup, so the cache stays a couple dozen entries.
const CLOSER_RES = new Map<string, RegExp>()

function closerRe(name: string): RegExp {
    let re = CLOSER_RES.get(name)
    if (!re) {
        re = new RegExp(`</${name}\\s*>`)
        CLOSER_RES.set(name, re)
    }
    return re
}

const KNOWN_TAG_NAMES = [...Object.keys(OBJECT_KIND_DATA), ...Object.keys(OBJECT_KIND_ALIASES)]
const RE_ID_ATTR = /(?:^|\s)id\s*=/

function inSpan(position: number, spans: Span[]): boolean {
    return spans.some((span) => span.start <= position && position < span.end)
}

/**
 * Could this partial tag fragment still become a tag the renderer would touch?
 * Either the name so far is a prefix of a registered kind, or the fragment
 * already carries an `id` attribute (the object-shaped improvisations the
 * renderer keeps the label of). Anything else — `plain <widget` — is prose.
 */
function partialCouldBecomeTag(fragment: string): boolean {
    const name = /^<([a-z][\w-]*)/.exec(fragment)?.[1] ?? ''
    if (/\s/.test(fragment)) {
        // The name is complete; only the attributes are still streaming.
        return resolveKind(name) !== null || RE_ID_ATTR.test(fragment.slice(1 + name.length))
    }
    return KNOWN_TAG_NAMES.some((known) => known.startsWith(name))
}

/**
 * Index where a trailing object tag that has not finished streaming in begins,
 * or null. Mirrors the Slack relay's `split_incomplete_tag_suffix`, minus its
 * fence holding: the Slack splitter is stateless across flushes and must keep
 * an open fence buffered, while here the whole text re-renders every chunk and
 * `scanCode` already keeps tags inside an open fence literal.
 *
 * Only the region after `searchFrom` (the end of the last complete tag) is
 * considered, so tag-shaped text inside a complete tag's body — SQL quoting
 * `'<insight id="x">'` — never splits the text. Openers inside code spans are
 * prose, not streaming tags.
 */
function heldSuffixStart(text: string, spans: Span[], searchFrom: number): number | null {
    const lastLt = text.lastIndexOf('<')
    if (
        lastLt >= searchFrom &&
        !inSpan(lastLt, spans) &&
        !text.slice(lastLt).includes('>') &&
        RE_PARTIAL_OPEN_TAG.test(text.slice(lastLt)) &&
        partialCouldBecomeTag(text.slice(lastLt))
    ) {
        return lastLt
    }
    let lastOpen: { start: number; end: number; name: string } | null = null
    for (const match of text.matchAll(RE_OPEN_TAG)) {
        if (match.index < searchFrom || match[3] !== '>' || inSpan(match.index, spans)) {
            continue
        }
        if (resolveKind(match[1]) !== null || RE_ID_ATTR.test(match[2])) {
            lastOpen = { start: match.index, end: match.index + match[0].length, name: match[1] }
        }
    }
    if (lastOpen !== null && !closerRe(lastOpen.name).test(text.slice(lastOpen.end))) {
        return lastOpen.start
    }
    return null
}

/**
 * Replace agent object tags in `text` with markdown links into the project.
 *
 * `projectBase` is the app path every object link hangs off, e.g. `/project/2`.
 * Text with no tags passes through unchanged, so the transform is safe to run
 * on every render, including on text it already rewrote.
 */
export function rewriteAgentObjectTags(text: string, projectBase: string): string {
    if (!text.includes('<')) {
        return text
    }
    const spans = scanCode(text)
    const tags = scanTags(text, spans)
    // Complete tags all end before the held region starts, so the slice below
    // cannot invalidate them.
    const searchFrom = tags.length > 0 ? tags[tags.length - 1].end : 0
    const held = heldSuffixStart(text, spans, searchFrom)
    if (held !== null && text.length - held <= MAX_HELD_SUFFIX) {
        text = text.slice(0, held)
    }
    if (tags.length === 0) {
        return text
    }
    const base = projectBase.replace(/\/$/, '')
    let output = ''
    let position = 0
    let needsParagraphBreak = false
    for (const tag of tags) {
        const rendered = renderTag(tag, base)
        if (rendered === null) {
            continue
        }
        let before = text.slice(position, tag.start)
        if (needsParagraphBreak) {
            // The fence must end its line, so anything after it starts a new paragraph.
            before = '\n\n' + before.replace(/^\n+/, '')
        }
        needsParagraphBreak = false
        output += before
        if (rendered.includes('\n')) {
            // A fenced block only survives markdown conversion as its own paragraph.
            // A list marker whose only content is this block would be left as an
            // empty bullet once the block moves out, so the bare marker goes too.
            output = output.replace(/(^|\n)[ \t]{0,3}(?:[-*+]|\d{1,9}[.)])[ \t]*$/, '$1')
            if (output.trim() && !output.endsWith('\n\n')) {
                output = output.replace(/\n+$/, '') + '\n\n'
            }
            needsParagraphBreak = true
        }
        output += rendered
        position = tag.end
    }
    let rest = text.slice(position)
    if (needsParagraphBreak && rest.trim()) {
        rest = '\n\n' + rest.replace(/^\n+/, '')
    }
    return output + rest
}
