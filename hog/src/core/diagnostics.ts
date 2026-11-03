import { escapeControls, type Output, type Style } from './output'
import { plural } from './text'

// One problem the server found in a piece of source text. The offsets count Unicode code points,
// as Python strings do, and are null when the problem has no location.
export interface Diagnostic {
    message: string
    start?: number | null
    end?: number | null
}

export interface Diagnostics {
    errors?: Diagnostic[] | null
    warnings?: Diagnostic[] | null
    notices?: Diagnostic[] | null
}

export function printDiagnostics(out: Output, source: string, diagnostics: Diagnostics): void {
    const groups: { label: string; style: Style; items: Diagnostic[] }[] = [
        { label: 'error', style: 'red', items: diagnostics.errors ?? [] },
        { label: 'warning', style: 'yellow', items: diagnostics.warnings ?? [] },
        { label: 'notice', style: 'cyan', items: diagnostics.notices ?? [] },
    ]
    const chars = Array.from(source)
    for (const group of groups) {
        for (const item of group.items) {
            out.line(`${out.style(group.label, group.style, 'bold')}: ${escapeControls(item.message)}`)
            if (item.start == null) {
                continue
            }
            const { line, column, before, marked, after } = locate(chars, item.start, item.end ?? item.start + 1)
            const gutter = `${line} | `
            out.line(out.style(`  --> line ${line}, column ${column}`, 'dim'))
            out.line(`  ${out.style(gutter, 'dim')}${printable(before + marked + after)}`)
            const pad = ' '.repeat(gutter.length + Bun.stringWidth(printable(before)))
            out.line(`  ${pad}${out.style('^'.repeat(Math.max(1, Bun.stringWidth(printable(marked)))), group.style)}`)
        }
    }
    const errors = diagnostics.errors?.length ?? 0
    const summary = groups.map((group) => plural(group.items.length, group.label)).join(', ')
    out.line(errors === 0 ? out.style(`Query is valid (${summary})`, 'green') : out.style(summary, 'red'))
}

// Tabs become spaces so the caret line stays aligned with the source line.
function printable(text: string): string {
    return escapeControls(text.replaceAll('\t', ' '))
}

function locate(
    chars: string[],
    start: number,
    end: number
): { line: number; column: number; before: string; marked: string; after: string } {
    const offset = Math.min(Math.max(start, 0), chars.length)
    // Unlike a string's, an array's lastIndexOf reads -1 as the last index.
    const lineStart = offset === 0 ? 0 : chars.lastIndexOf('\n', offset - 1) + 1
    const newline = chars.indexOf('\n', offset)
    const lineEnd = newline === -1 ? chars.length : newline
    const markEnd = Math.min(Math.max(end, offset), lineEnd)
    let line = 1
    for (let index = 0; index < lineStart; index++) {
        line += chars[index] === '\n' ? 1 : 0
    }
    return {
        line,
        column: offset - lineStart + 1,
        before: chars.slice(lineStart, offset).join(''),
        marked: chars.slice(offset, markEnd).join(''),
        after: chars.slice(markEnd, lineEnd).join(''),
    }
}
