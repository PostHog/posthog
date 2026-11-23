// A stack folder and the CLI that evaluates it each load their own copy of this module, so a
// definition is recognised by a registered symbol, never with `instanceof`.
export const DEFINITION: unique symbol = Symbol.for('posthog.define.definition')
export const REF_TARGET: unique symbol = Symbol.for('posthog.define.ref-target')

export const DEFINITION_VERSION = 1

export interface DefinitionOrigin {
    // The file that called the define function, as an absolute path. The description records it
    // relative to the repository root.
    file?: string
    // Every file on the call stack at that point, nearest first.
    frames?: readonly string[]
    // Set on an insight that a dashboard made from one of its tiles.
    dashboard?: string
    tile?: string
}

export interface Definition<Kind extends string = string, Key extends string = string, Body = unknown> {
    readonly [DEFINITION]: typeof DEFINITION_VERSION
    readonly kind: Kind
    readonly key: Key
    readonly body: Body
    readonly origin: DefinitionOrigin
}

export type RefAttr = 'id' | 'short_id' | 'key' | 'name'

// The shape a reference has in the description. `ref()` also keeps the definition it points at
// under a symbol, which JSON leaves out, so evaluation can include a definition no export names.
export interface Ref<Kind extends string = string> {
    $ref: { kind: Kind; key: string; attr?: RefAttr }
    readonly [REF_TARGET]?: Definition<Kind>
}

export interface SecretRef {
    $secret: string
}

// A position that takes another entity's id takes its definition, or a ref to it.
export type RefTo<Kind extends string> = Definition<Kind> | Ref<Kind>

export function isDefinition(value: unknown): value is Definition {
    return (
        typeof value === 'object' &&
        value !== null &&
        (value as Record<PropertyKey, unknown>)[DEFINITION] === DEFINITION_VERSION
    )
}

export function isRef(value: unknown): value is Ref {
    if (typeof value !== 'object' || value === null || !('$ref' in value)) {
        return false
    }
    const target = (value as { $ref: unknown }).$ref
    return typeof target === 'object' && target !== null && 'kind' in target && 'key' in target
}

export function ref<Kind extends string>(definition: Definition<Kind>, attr?: RefAttr): Ref<Kind>
export function ref<Kind extends string>(kind: Kind, key: string, attr?: RefAttr): Ref<Kind>
export function ref<Kind extends string>(
    target: Definition<Kind> | Kind,
    keyOrAttr?: string,
    attr?: RefAttr
): Ref<Kind> {
    if (typeof target === 'string') {
        if (keyOrAttr === undefined) {
            throw new TypeError(`ref('${target}') needs the key of the ${target} it points at.`)
        }
        return { $ref: { kind: target, key: keyOrAttr, ...(attr && attr !== 'id' ? { attr } : {}) } }
    }
    const chosen = keyOrAttr as RefAttr | undefined
    const reference: Ref<Kind> = {
        $ref: { kind: target.kind, key: target.key, ...(chosen && chosen !== 'id' ? { attr: chosen } : {}) },
    }
    Object.defineProperty(reference, REF_TARGET, { value: target, enumerable: false })
    return reference
}

export function secret(name: string): SecretRef {
    return { $secret: name }
}

const DEFINE_FOLDER = folderOf(import.meta.url)
// With source maps, frames name the TypeScript source instead of the built file next to it.
const DEFINE_FOLDERS = [DEFINE_FOLDER, DEFINE_FOLDER.replace(/\/dist\/define\/$/, '/src/define/')]

function folderOf(url: string): string {
    const path = url.startsWith('file://') ? decodeURIComponent(new URL(url).pathname) : url
    return path.slice(0, path.lastIndexOf('/') + 1)
}

const LOCATION = /:\d+:\d+\)?$/
const PATH_STARTS = ['(file://', '(/', 'at file://', 'at /']

// The file of one stack frame, or undefined for a frame without one, such as native code.
export function frameFile(line: string): string | undefined {
    const trimmed = line.trim()
    if (!LOCATION.test(trimmed)) {
        return undefined
    }
    const drive = /(?:\(|at )([A-Za-z]:[\\/])/.exec(trimmed)
    const starts = PATH_STARTS.map((start) => trimmed.indexOf(start)).filter((index) => index >= 0)
    const first = Math.min(...starts, drive ? drive.index : Number.POSITIVE_INFINITY)
    if (!Number.isFinite(first)) {
        return undefined
    }
    const from = trimmed.slice(first).replace(/^\(|^at /, '')
    const path = from.replace(LOCATION, '')
    return path.startsWith('file://') ? decodeURIComponent(new URL(path).pathname) : path
}

// Every file on the call stack outside this module, nearest first. Evaluation records the first
// one inside the stack folder, and leaves the source out when none is.
export function callerFiles(): string[] {
    // A V8 and JavaScriptCore setting, which browser type libraries don't declare.
    const errors = Error as { stackTraceLimit?: number | undefined }
    const limit = errors.stackTraceLimit
    errors.stackTraceLimit = 50
    let stack = ''
    try {
        stack = new Error().stack ?? ''
    } finally {
        errors.stackTraceLimit = limit
    }
    const files: string[] = []
    for (const line of stack.split('\n').slice(1)) {
        const file = frameFile(line)
        if (file && !DEFINE_FOLDERS.some((folder) => file.startsWith(folder)) && !files.includes(file)) {
            files.push(file)
        }
    }
    return files
}

export function callerFile(): string | undefined {
    return callerFiles()[0]
}

export function defineKind<const Kind extends string, const Key extends string, Body, Extra extends object = {}>(
    kind: Kind,
    key: Key,
    body: Body,
    origin: Omit<DefinitionOrigin, 'file'> = {},
    extra?: Extra
): Definition<Kind, Key, Body> & Extra {
    const frames = callerFiles()
    return Object.freeze({
        ...extra,
        [DEFINITION]: DEFINITION_VERSION,
        kind,
        key,
        body,
        origin: Object.freeze({ ...origin, ...(frames.length > 0 ? { file: frames[0], frames } : {}) }),
    }) as Definition<Kind, Key, Body> & Extra
}

export const ISSUES: unique symbol = Symbol.for('posthog.define.issues')

// A problem a builder found while it built a value, such as a column the model doesn't declare.
// Evaluation reports it with the path of the value it is attached to.
export interface DefineIssue {
    code: string
    message: string
    // Below the value the issue is attached to.
    path?: string
}

// Attaches under a symbol, so the value stays plain JSON and the issue travels with it.
export function withIssues<T extends object>(value: T, issues: readonly DefineIssue[]): T {
    if (issues.length === 0) {
        return value
    }
    const existing = (value as { [ISSUES]?: DefineIssue[] })[ISSUES] ?? []
    Object.defineProperty(value, ISSUES, { value: [...existing, ...issues], enumerable: false, configurable: true })
    return value
}

export function issuesOf(value: unknown): readonly DefineIssue[] {
    if (typeof value !== 'object' || value === null) {
        return []
    }
    return (value as { [ISSUES]?: DefineIssue[] })[ISSUES] ?? []
}

export const DEPENDS: unique symbol = Symbol.for('posthog.define.depends')

// Definitions a value reads by name rather than through a ref, such as a model whose table a query
// selects from. Evaluation records them as the resource's `depends_on`, so the engine creates them first.
export function withDependencies<T extends object>(value: T, definitions: readonly Definition[]): T {
    if (definitions.length === 0) {
        return value
    }
    const existing = (value as { [DEPENDS]?: Definition[] })[DEPENDS] ?? []
    const merged = [...existing, ...definitions.filter((definition) => !existing.includes(definition))]
    Object.defineProperty(value, DEPENDS, { value: merged, enumerable: false, configurable: true })
    return value
}

export function dependenciesOf(value: unknown): readonly Definition[] {
    if (typeof value !== 'object' || value === null) {
        return []
    }
    return (value as { [DEPENDS]?: Definition[] })[DEPENDS] ?? []
}
