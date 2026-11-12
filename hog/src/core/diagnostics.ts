import { z } from 'zod'

import { escapeControls, type Output, type Style } from './output'
import { plural } from './text'

// One problem the server found in a piece of source text. The offsets count Unicode code points,
// as Python strings do, and are null when the problem has no location.
const DiagnosticMessage = z.looseObject({ message: z.string(), start: z.number().nullish(), end: z.number().nullish() })

type DiagnosticMessage = z.infer<typeof DiagnosticMessage>

export const DiagnosticsReport = z.looseObject({
    errors: z.array(DiagnosticMessage).nullish(),
    warnings: z.array(DiagnosticMessage).nullish(),
    notices: z.array(DiagnosticMessage).nullish(),
})

export type DiagnosticsReport = z.infer<typeof DiagnosticsReport>

export function printDiagnostics(out: Output, source: string, diagnostics: DiagnosticsReport): void {
    const groups: { label: string; style: Style; items: DiagnosticMessage[] }[] = [
        { label: 'error', style: 'red', items: diagnostics.errors ?? [] },
        { label: 'warning', style: 'yellow', items: diagnostics.warnings ?? [] },
        { label: 'notice', style: 'cyan', items: diagnostics.notices ?? [] },
    ]
    const errors = diagnostics.errors?.length ?? 0
    const summary = groups.map((group) => plural(group.items.length, group.label)).join(', ')
    out.report(
        errors === 0 ? { result: `Query is valid (${summary})` } : { status: 'failed', result: `Query has ${summary}` }
    )

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
