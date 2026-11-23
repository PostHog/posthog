import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import type { JsonValue } from '../types.js'
import { resourceId } from './evaluate.js'
import { findRoot, loadStack } from './load.js'
import { findCompiler } from './typecheck.js'

// One field that differs between what the stack pushed and what PostHog holds now, as `diff`
// reports it.
export interface DriftField {
    path: string
    pushed: JsonValue
    found: JsonValue
}

export interface Drift {
    kind: string
    key: string
    fields: DriftField[]
}

export interface FoldedField {
    kind: string
    key: string
    // Relative to the repository root.
    file: string
    path: string
    before: JsonValue
    after: JsonValue
}

export interface ManualField {
    kind: string
    key: string
    file?: string
    path: string
    pushed: JsonValue
    found: JsonValue
    // Why the field could not be rewritten, for the person or agent who will.
    reason: string
}

// The parts of the TypeScript syntax tree this file reads, from the project's own compiler.
interface Node {
    kind: number
    getStart(file?: SourceFile): number
    getEnd(): number
    getText(file?: SourceFile): string
    forEachChild<T>(visit: (node: Node) => T | undefined): T | undefined
}

interface SourceFile extends Node {
    text: string
}

interface Syntax {
    createSourceFile(name: string, text: string, target: number, setParents: boolean): SourceFile
    ScriptTarget: { Latest: number }
    SyntaxKind: Record<string, number>
}

interface Located {
    file: string
    absolute: string
}

// Builders that move fields: the body path a field has, and the path it has in the builder's options.
const BUILDER_PATHS: Readonly<Record<string, readonly [string, string][]>> = {
    hogql: [
        ['query.source.query', 'query'],
        ['query.display', 'display'],
        ['query.chartSettings', 'chartSettings'],
        ['query.tableSettings', 'tableSettings'],
    ],
    trend: [['query.source', '']],
    funnel: [
        ['query.source.series', 'steps'],
        ['query.source', ''],
    ],
}

function segments(path: string): (string | number)[] {
    return path
        .split(/\.|(?=\[)/)
        .filter(Boolean)
        .map((part) => (part.startsWith('[') ? Number(part.slice(1, -1)) : part))
}

function literalValue(ts: Syntax, node: Node, file: SourceFile): { value: JsonValue } | undefined {
    const kinds = ts.SyntaxKind
    const text = node.getText(file)
    if (node.kind === kinds.StringLiteral || node.kind === kinds.NoSubstitutionTemplateLiteral) {
        return { value: (node as unknown as { text: string }).text }
    }
    if (node.kind === kinds.NumericLiteral) {
        return { value: Number(text) }
    }
    if (node.kind === kinds.PrefixUnaryExpression && /^-\s*[0-9.]+$/.test(text)) {
        return { value: Number(text.replace(/\s/g, '')) }
    }
    if (node.kind === kinds.TrueKeyword || node.kind === kinds.FalseKeyword) {
        return { value: node.kind === kinds.TrueKeyword }
    }
    if (node.kind === kinds.NullKeyword) {
        return { value: null }
    }
    return undefined
}

function literalText(value: JsonValue, original: string): string | undefined {
    if (typeof value === 'string') {
        const quote = original.startsWith('"') ? '"' : "'"
        if (value.includes('\n')) {
            return `\`${value.replace(/\\/g, '\\\\').replace(/`/g, '\\`').replace(/\$\{/g, '\\${')}\``
        }
        const escaped = JSON.stringify(value).slice(1, -1)
        return quote === '"' ? `"${escaped}"` : `'${escaped.replace(/\\"/g, '"').replace(/'/g, "\\'")}'`
    }
    if (typeof value === 'number' || typeof value === 'boolean' || value === null) {
        return JSON.stringify(value)
    }
    return undefined
}

function children(node: Node): Node[] {
    const found: Node[] = []
    node.forEachChild((child) => {
        found.push(child)
        return undefined
    })
    return found
}

interface PropertyNode extends Node {
    name: Node
    initializer: Node
}

// The value written for `name` in an object literal, or undefined when the literal doesn't write it
// plainly, for example through a spread.
function propertyOf(ts: Syntax, object: Node, name: string, file: SourceFile): Node | undefined {
    for (const child of children(object)) {
        if (child.kind !== ts.SyntaxKind.PropertyAssignment) {
            continue
        }
        const property = child as PropertyNode
        const written = property.name.getText(file).replace(/^['"`]|['"`]$/g, '')
        if (written === name) {
            return property.initializer
        }
    }
    return undefined
}

function callName(ts: Syntax, node: Node, file: SourceFile): string | undefined {
    if (node.kind !== ts.SyntaxKind.CallExpression) {
        return undefined
    }
    const [callee] = children(node)
    return callee?.getText(file)
}

function callArguments(node: Node): Node[] {
    return [...((node as unknown as { arguments: Node[] }).arguments ?? [])]
}

// The `<fn>('key', ...)` call that declares the definition.
function findDeclaration(ts: Syntax, file: SourceFile, key: string): Node | undefined {
    let found: Node | undefined
    const visit = (node: Node): void => {
        if (found) {
            return
        }
        if (node.kind === ts.SyntaxKind.CallExpression) {
            const [first] = callArguments(node)
            const literal = first ? literalValue(ts, first, file) : undefined
            if (literal && literal.value === key) {
                found = node
                return
            }
        }
        node.forEachChild((child) => {
            visit(child)
            return undefined
        })
    }
    visit(file)
    return found
}

function locate(ts: Syntax, start: Node, path: string, file: SourceFile): { node?: Node; reason?: string } {
    let node: Node | undefined = start
    let remaining = segments(path)
    while (remaining.length > 0 && node) {
        if (node.kind === ts.SyntaxKind.CallExpression) {
            const name = callName(ts, node, file) ?? ''
            const [options] = callArguments(node)
            if (!options || options.kind !== ts.SyntaxKind.ObjectLiteralExpression) {
                return { reason: `the value comes from a call to ${name}, not a literal` }
            }
            const joined = remaining.map(String).join('.')
            const mapping = BUILDER_PATHS[name]?.find(([from]) => joined === from || joined.startsWith(`${from}.`))
            if (mapping) {
                remaining = [...segments(mapping[1]), ...remaining.slice(segments(mapping[0]).length)]
            }
            node = options
            continue
        }
        const [next, ...rest] = remaining
        if (node.kind === ts.SyntaxKind.ObjectLiteralExpression && typeof next === 'string') {
            node = propertyOf(ts, node, next, file)
            if (!node) {
                return { reason: `the definition doesn't write ${next} as a plain field` }
            }
        } else if (node.kind === ts.SyntaxKind.ArrayLiteralExpression && typeof next === 'number') {
            const elements: Node[] = (node as unknown as { elements: Node[] }).elements
            if (elements.slice(0, next + 1).some((element) => element.kind === ts.SyntaxKind.SpreadElement)) {
                return { reason: 'the list is built with a spread' }
            }
            node = elements[next]
        } else {
            return { reason: 'the value is computed in code' }
        }
        remaining = rest
    }
    return node ? { node } : { reason: 'the field is not in the definition' }
}

// Writes each drifted value into the definition where the source holds it as a literal equal to the
// pushed value, and returns the rest for a person or agent to change by hand.
export async function foldDrift(
    dir: string,
    drift: readonly Drift[]
): Promise<{ applied: FoldedField[]; manual: ManualField[] }> {
    const root = findRoot(dir)
    const loaded = await loadStack(dir, { root, skipSchemas: true })
    const ts = (await findCompiler(dir)) as unknown as Syntax | undefined
    const applied: FoldedField[] = []
    const manual: ManualField[] = []
    const edits = new Map<string, { start: number; end: number; text: string }[]>()
    const sources = new Map<string, SourceFile>()

    for (const item of [...drift].sort((a, b) => resourceId(a.kind, a.key).localeCompare(resourceId(b.kind, b.key)))) {
        const fileName = loaded.origins.get(resourceId(item.kind, item.key))?.file
        const location: Located | undefined = fileName ? { file: fileName, absolute: join(root, fileName) } : undefined
        for (const field of item.fields) {
            const leave = (reason: string): void => {
                manual.push({
                    kind: item.kind,
                    key: item.key,
                    ...(location ? { file: location.file } : {}),
                    path: field.path,
                    pushed: field.pushed,
                    found: field.found,
                    reason,
                })
            }
            if (!location) {
                leave('check could not find the file that declares this definition')
                continue
            }
            if (!ts) {
                leave('this project has no TypeScript compiler to edit the file with')
                continue
            }
            let source = sources.get(location.absolute)
            if (!source) {
                source = ts.createSourceFile(
                    location.absolute,
                    readFileSync(location.absolute, 'utf8'),
                    ts.ScriptTarget.Latest,
                    true
                )
                sources.set(location.absolute, source)
            }
            const declaration = findDeclaration(ts, source, item.key)
            const [, options] = declaration ? callArguments(declaration) : []
            if (!declaration || !options) {
                leave(`the file has no call that declares ${item.key} with a literal key`)
                continue
            }
            const { node, reason } = locate(ts, options, field.path, source)
            if (!node) {
                leave(reason ?? 'the field is not in the definition')
                continue
            }
            const literal = literalValue(ts, node, source)
            if (!literal) {
                leave('the value is computed in code, not written as a literal')
                continue
            }
            if (JSON.stringify(literal.value) !== JSON.stringify(field.pushed)) {
                leave('the file no longer holds the pushed value, so it changed since the push')
                continue
            }
            const text = literalText(field.found, node.getText(source))
            if (text === undefined) {
                leave('the value PostHog holds is not a single literal')
                continue
            }
            const list = edits.get(location.absolute) ?? []
            list.push({ start: node.getStart(source), end: node.getEnd(), text })
            edits.set(location.absolute, list)
            applied.push({
                kind: item.kind,
                key: item.key,
                file: location.file,
                path: field.path,
                before: field.pushed,
                after: field.found,
            })
        }
    }
    for (const [absolute, list] of edits) {
        let text = (sources.get(absolute) as SourceFile).text
        for (const edit of [...list].sort((a, b) => b.start - a.start)) {
            text = `${text.slice(0, edit.start)}${edit.text}${text.slice(edit.end)}`
        }
        writeFileSync(absolute, text)
    }
    return { applied, manual }
}
