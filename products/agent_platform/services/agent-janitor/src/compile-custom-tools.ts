/**
 * Custom-tool upload pipeline: parse → AST shape check → banned-construct
 * check → capability walk → esbuild → emit `compiled.js`. Runs inside the
 * `PUT /tools/:id` handler so failures surface at upload time, not at
 * session-start.
 *
 * Three AST passes:
 *
 *   1. **Shape check** — pure source-text analysis via the TypeScript
 *      compiler API. Walks the syntax tree without executing user code.
 *      Confirms exactly one `export default <ObjectLiteral>` with an
 *      `actions` property whose `default` entry is a function-shaped node.
 *      No `vm.runInContext`, no Modal sandbox — nothing runs, nothing to
 *      sandbox.
 *
 *   2. **Banned-construct check** — defense-in-depth rejection of modules
 *      and constructs with no legitimate use in a compute-only tool. The
 *      sandbox itself blocks network and process spawning, but a
 *      compile-time error gives the author a friendly message at write
 *      time instead of a cryptic runtime failure. Mirrors the
 *      egress-via-native-tools doctrine in `docs/custom-tools.md`.
 *
 *   3. **Capability extraction** — collects metadata the authoring UI
 *      surfaces on each tool (secret names referenced via
 *      `ctx.secrets.ref(...)`). Best-effort; only static string-literal
 *      args are picked up.
 *
 * If shape + banned checks pass, **esbuild transform** runs (TS → CJS,
 * `node20`, the same output the runner has loaded since day one).
 *
 * Failures bubble up as structured `ToolCompileError` objects. Each carries
 * a `kind` discriminator + a one-line `message` the caller (and the
 * concierge model) can surface verbatim.
 */

import { transform as esbuildTransform } from 'esbuild'
import ts from 'typescript'

export type ToolCompileErrorKind =
    | 'parse_failed'
    | 'ast_no_default_export'
    | 'ast_default_not_object'
    | 'ast_missing_actions'
    | 'ast_actions_not_object'
    | 'ast_missing_default_action'
    | 'ast_default_action_not_callable'
    | 'ast_dynamic_export'
    | 'banned_module_import'
    | 'banned_eval'
    | 'transform_failed'

export interface ToolCompileError {
    kind: ToolCompileErrorKind
    message: string
    /** Source position where the error was detected, if known (1-based). */
    line?: number
    column?: number
}

/**
 * Capabilities the authoring UI surfaces on each tool. Best-effort: pulled
 * from a static AST walk over the source, so dynamic constructions (a
 * secret name in a variable, computed property access) won't appear. The
 * `dynamic_secret_refs` flag is true when at least one `ctx.secrets.ref()`
 * call had a non-string-literal argument — the author needs to know there
 * are references we couldn't enumerate.
 */
export interface ToolCapabilities {
    /** Distinct secret names referenced via `ctx.secrets.ref('NAME')`. Sorted. */
    secret_refs: string[]
    /** True when at least one `ctx.secrets.ref(...)` call had a non-literal arg. */
    dynamic_secret_refs: boolean
}

export interface CompileTypedToolResult {
    ok: boolean
    /** When ok: the CJS-shaped compiled.js the runner will load at session start. */
    compiled_js?: string
    /** Always present; empty when ok. */
    errors: ToolCompileError[]
    /** When ok: best-effort capability metadata for the authoring UI. */
    capabilities?: ToolCapabilities
}

/**
 * Node stdlib modules a compute-only tool has no legitimate use for. The
 * sandbox already blocks network reach and process spawning at the OS
 * level; this list lets us reject at author time with a friendly message
 * pointing at the right alternative. Cover both `node:foo` and bare `foo`
 * spellings (Node accepts both for stdlib).
 *
 * Modules deliberately NOT banned: `fs`, `path`, `crypto`, `util`, `events`,
 * `stream`, `url`, `querystring`, `buffer`, `perf_hooks`, `zlib`, `os`,
 * `assert`, `console`, `string_decoder` — useful for pure compute and have
 * no egress side effects.
 */
const BANNED_NODE_MODULES = new Set([
    'http',
    'https',
    'http2',
    'net',
    'dgram',
    'dns',
    'dns/promises',
    'tls',
    'child_process',
    'cluster',
    'worker_threads',
    'vm',
    // Escape-hatch / arbitrary-code modules. None has a legit use in a
    // compute-only tool, and the first two are particularly dangerous:
    // `inspector` exposes the V8 inspector (full eval + opens a debugger
    // port — egress channel), `module` lets you reconstruct `require` via
    // `module._load`. The sandbox still contains them at runtime; the ban
    // keeps the friendly compile-time error story honest.
    'inspector',
    'inspector/promises',
    'module',
    'repl',
    'wasi',
])

function isBannedModuleSpecifier(spec: string): boolean {
    const stripped = spec.startsWith('node:') ? spec.slice('node:'.length) : spec
    return BANNED_NODE_MODULES.has(stripped)
}

function bannedModuleMessage(spec: string): string {
    return `\`${spec}\` cannot be imported from a custom tool — the sandbox blocks network and process spawning. For external HTTP, use the \`@posthog/http-request\` native tool with a host-pinned secret (see docs/custom-tools.md).`
}

/**
 * Validate + compile one tool's source. Pure (no I/O, no globals); the
 * caller writes the result to the bundle store when ok.
 */
export async function compileTypedTool(args: { tool_id: string; source: string }): Promise<CompileTypedToolResult> {
    const sf = ts.createSourceFile(
        `${args.tool_id}.ts`,
        args.source,
        ts.ScriptTarget.ES2022,
        /* setParentNodes */ true,
        ts.ScriptKind.TS
    )

    // Run shape + banned-construct checks together so authors see every
    // diagnostic in one round-trip instead of fixing in waves. Shape errors
    // come first in the merged list (they're the more foundational signal,
    // and the existing single-error tests assert errors[0].kind).
    const allErrors = [...checkExportShape(sf), ...checkBannedConstructs(sf)]
    if (allErrors.length > 0) {
        return { ok: false, errors: allErrors }
    }

    const capabilities = extractCapabilities(sf)

    try {
        const out = await esbuildTransform(args.source, {
            loader: 'ts',
            format: 'cjs',
            target: 'node20',
        })
        return { ok: true, compiled_js: out.code, errors: [], capabilities }
    } catch (err) {
        return {
            ok: false,
            errors: [
                {
                    kind: 'transform_failed',
                    message: `esbuild failed: ${(err as Error).message.split('\n')[0]}`,
                },
            ],
        }
    }
}

// ─── AST shape check ─────────────────────────────────────────────────

/**
 * Walk the syntax tree, confirm there's exactly one `export default
 * <ObjectLiteral>` with an `actions.default` function-shaped property.
 * No type-checking, no symbol resolution — the source-file parse is enough.
 */
function checkExportShape(sf: ts.SourceFile): ToolCompileError[] {
    const errors: ToolCompileError[] = []

    // Collect:
    //   1. `export default <expr>`  — `ExportAssignment` with !isExportEquals
    //   2. `export default function foo() {}` / `export default class Bar {}`
    //      — these are `FunctionDeclaration` / `ClassDeclaration` nodes with
    //      `export` + `default` modifiers, NOT ExportAssignments. Easy to
    //      miss; the bare-function concierge foot-gun ships exactly this
    //      shape.
    const defaultExports: { node: ts.Node; expr: ts.Expression | null }[] = []
    for (const stmt of sf.statements) {
        if (ts.isExportAssignment(stmt) && !stmt.isExportEquals) {
            defaultExports.push({ node: stmt, expr: stmt.expression })
        } else if (
            (ts.isFunctionDeclaration(stmt) || ts.isClassDeclaration(stmt)) &&
            hasModifier(stmt, ts.SyntaxKind.ExportKeyword) &&
            hasModifier(stmt, ts.SyntaxKind.DefaultKeyword)
        ) {
            // The function/class declaration IS the export — there's no
            // wrapped expression, so we keep `expr: null` and the caller
            // treats it as "default export but not an object literal".
            defaultExports.push({ node: stmt, expr: null })
        }
    }

    if (defaultExports.length === 0) {
        errors.push({
            kind: 'ast_no_default_export',
            message: 'tool source must `export default { actions: { default: fn } }` — no `export default` found',
        })
        return errors
    }
    if (defaultExports.length > 1) {
        const dup = defaultExports[1].node
        const pos = sf.getLineAndCharacterOfPosition(dup.getStart(sf))
        errors.push({
            kind: 'ast_no_default_export',
            message: 'tool source must have exactly one `export default` — exactly one found is required',
            line: pos.line + 1,
            column: pos.character + 1,
        })
        return errors
    }

    // `export default function foo() {}` or `export default class Bar {}` —
    // these are never the right shape. Report up front.
    if (defaultExports[0].expr === null) {
        const node = defaultExports[0].node
        const pos = sf.getLineAndCharacterOfPosition(node.getStart(sf))
        errors.push({
            kind: 'ast_default_not_object',
            message:
                'tool source must export an object, not a bare function or class. Wrap as `export default { actions: { default: <your function> } }`',
            line: pos.line + 1,
            column: pos.character + 1,
        })
        return errors
    }

    const expr = unwrap(defaultExports[0].expr)

    if (!ts.isObjectLiteralExpression(expr)) {
        const pos = sf.getLineAndCharacterOfPosition(expr.getStart(sf))
        if (ts.isFunctionExpression(expr) || ts.isArrowFunction(expr)) {
            errors.push({
                kind: 'ast_default_not_object',
                message:
                    'tool source must export an object, not a bare function. Wrap as `export default { actions: { default: <your function> } }`',
                line: pos.line + 1,
                column: pos.character + 1,
            })
        } else if (ts.isCallExpression(expr) || ts.isNewExpression(expr) || ts.isIdentifier(expr)) {
            errors.push({
                kind: 'ast_dynamic_export',
                message:
                    'tool definitions must be statically declared object literals. `export default makeTool()` / factory calls / identifier references are not allowed — the platform analyses the export shape ahead of run-time.',
                line: pos.line + 1,
                column: pos.character + 1,
            })
        } else {
            errors.push({
                kind: 'ast_default_not_object',
                message: `tool source must export an object literal — got ${ts.SyntaxKind[expr.kind]}`,
                line: pos.line + 1,
                column: pos.character + 1,
            })
        }
        return errors
    }

    const actionsProp = findProperty(expr, 'actions')
    if (!actionsProp) {
        errors.push({
            kind: 'ast_missing_actions',
            message: 'tool export object is missing required `actions` property — write `{ actions: { default: fn } }`',
        })
        return errors
    }

    const actionsValue = unwrap(actionsProp.initializer)
    if (!ts.isObjectLiteralExpression(actionsValue)) {
        const pos = sf.getLineAndCharacterOfPosition(actionsValue.getStart(sf))
        errors.push({
            kind: 'ast_actions_not_object',
            message: `\`actions\` must be an object literal — got ${ts.SyntaxKind[actionsValue.kind]}`,
            line: pos.line + 1,
            column: pos.character + 1,
        })
        return errors
    }

    const defaultProp = findProperty(actionsValue, 'default')
    if (!defaultProp) {
        errors.push({
            kind: 'ast_missing_default_action',
            message:
                '`actions.default` is required — the runner always dispatches `action: "default"`. Add a `default: (args, ctx) => { ... }` entry inside `actions`.',
        })
        return errors
    }

    const defaultValue = unwrap(defaultProp.initializer)
    if (!isCallable(defaultValue)) {
        const pos = sf.getLineAndCharacterOfPosition(defaultValue.getStart(sf))
        errors.push({
            kind: 'ast_default_action_not_callable',
            message: `\`actions.default\` must be a function (arrow or function expression). Got ${ts.SyntaxKind[defaultValue.kind]}.`,
            line: pos.line + 1,
            column: pos.character + 1,
        })
        return errors
    }

    return errors
}

function hasModifier(
    node: ts.FunctionDeclaration | ts.ClassDeclaration,
    kind: ts.SyntaxKind.ExportKeyword | ts.SyntaxKind.DefaultKeyword
): boolean {
    const mods = (node as ts.HasModifiers).modifiers
    if (!mods) {
        return false
    }
    for (const m of mods) {
        if (m.kind === kind) {
            return true
        }
    }
    return false
}

function unwrap(node: ts.Expression): ts.Expression {
    let cur: ts.Expression = node
    while (ts.isAsExpression(cur) || ts.isTypeAssertionExpression(cur) || ts.isParenthesizedExpression(cur)) {
        cur = (cur as ts.AsExpression | ts.TypeAssertion | ts.ParenthesizedExpression).expression
    }
    return cur
}

function findProperty(obj: ts.ObjectLiteralExpression, name: string): ts.PropertyAssignment | undefined {
    for (const member of obj.properties) {
        if (ts.isPropertyAssignment(member)) {
            const key = member.name
            if (ts.isIdentifier(key) && key.text === name) {
                return member
            }
            if (ts.isStringLiteral(key) && key.text === name) {
                return member
            }
        }
    }
    return undefined
}

function isCallable(node: ts.Expression): boolean {
    return ts.isArrowFunction(node) || ts.isFunctionExpression(node)
}

// ─── Banned-construct check ─────────────────────────────────────────
//
// Defense in depth. The sandbox enforces no-network + no-process-spawn at
// the OS layer (Docker `--network=none`, Modal `blockNetwork:true`,
// `--cap-drop=ALL`), so an `import 'http'` in a custom tool would just
// fail at runtime with a cryptic error. Reject at author time instead so
// the author sees a friendly message pointing at the right alternative
// (native tools with declared `allowed_hosts`).
//
// Recursive descent over the SourceFile so we catch banned constructs in
// nested scopes too — e.g. a `require('http')` inside a helper function
// shouldn't slip past a top-level-only check.

function checkBannedConstructs(sf: ts.SourceFile): ToolCompileError[] {
    const errors: ToolCompileError[] = []

    function visit(node: ts.Node): void {
        // `import 'http'` / `import x from 'http'` / `import { y } from 'http'`
        if (ts.isImportDeclaration(node)) {
            const spec = node.moduleSpecifier
            if (ts.isStringLiteral(spec) && isBannedModuleSpecifier(spec.text)) {
                const pos = sf.getLineAndCharacterOfPosition(spec.getStart(sf))
                errors.push({
                    kind: 'banned_module_import',
                    message: bannedModuleMessage(spec.text),
                    line: pos.line + 1,
                    column: pos.character + 1,
                })
            }
        }

        // `import('http')` — dynamic ESM import. esbuild leaves it as a runtime
        // call, but with no network it'd just fail; reject at author time.
        if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) {
            const [arg] = node.arguments
            if (arg && ts.isStringLiteral(arg) && isBannedModuleSpecifier(arg.text)) {
                const pos = sf.getLineAndCharacterOfPosition(arg.getStart(sf))
                errors.push({
                    kind: 'banned_module_import',
                    message: bannedModuleMessage(arg.text),
                    line: pos.line + 1,
                    column: pos.character + 1,
                })
            }
        }

        // `require('http')` — esbuild emits CJS, so `require` calls survive into
        // the runtime. We can't tell whether `require` here is the global Node
        // function or a user variable named the same; rejecting the literal-arg
        // form regardless is the conservative call.
        if (
            ts.isCallExpression(node) &&
            ts.isIdentifier(node.expression) &&
            node.expression.text === 'require' &&
            node.arguments.length >= 1
        ) {
            const [arg] = node.arguments
            if (ts.isStringLiteral(arg) && isBannedModuleSpecifier(arg.text)) {
                const pos = sf.getLineAndCharacterOfPosition(arg.getStart(sf))
                errors.push({
                    kind: 'banned_module_import',
                    message: bannedModuleMessage(arg.text),
                    line: pos.line + 1,
                    column: pos.character + 1,
                })
            }
        }

        // `eval(...)` — classic exfil-via-dynamic-construction pattern. With
        // banned imports above this is the obvious bypass; reject it too.
        if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === 'eval') {
            const pos = sf.getLineAndCharacterOfPosition(node.expression.getStart(sf))
            errors.push({
                kind: 'banned_eval',
                message:
                    '`eval(...)` is not allowed in a custom tool — dynamic code execution defeats the static-shape contract and the banned-import check.',
                line: pos.line + 1,
                column: pos.character + 1,
            })
        }

        // `new Function(...)` / `Function(...)` — semantically equivalent to
        // eval. Both forms `new Function('x')()` and `Function('x')()` work
        // in JS; check both call shapes.
        if (
            (ts.isNewExpression(node) || ts.isCallExpression(node)) &&
            ts.isIdentifier(node.expression) &&
            node.expression.text === 'Function'
        ) {
            const pos = sf.getLineAndCharacterOfPosition(node.expression.getStart(sf))
            const form = ts.isNewExpression(node) ? '`new Function(...)`' : '`Function(...)`'
            errors.push({
                kind: 'banned_eval',
                message: `${form} is not allowed in a custom tool — dynamic code construction defeats the static-shape contract.`,
                line: pos.line + 1,
                column: pos.character + 1,
            })
        }

        ts.forEachChild(node, visit)
    }

    visit(sf)
    return errors
}

// ─── Capability extraction ──────────────────────────────────────────
//
// Walks the source for `ctx.secrets.ref('NAME')` calls and collects the
// literal secret names. Pure static analysis with two precision dials:
//
//   - **Receiver match is tight**: only `ctx.secrets.ref(...)` is collected,
//     not `<anyIdent>.secrets.ref(...)`. The convention documented in
//     `docs/custom-tools.md` and in the `CustomToolContext` JSDoc names the
//     parameter `ctx`. False positives from unrelated `client.secrets.ref`
//     SDK chains would mislead the UI; the trade-off is that an author
//     renaming `ctx` loses the static list — that case still surfaces via
//     the `dynamic_secret_refs` flag below.
//
//   - **Dynamic flag is conservative**: set when we see *any* reference to
//     `ctx.secrets` that the static collector can't fully resolve — alias
//     (`const r = ctx.secrets.ref; r('X')`), destructure (`const {ref} =
//     ctx.secrets`), computed access (`ctx['secrets']['ref'](...)`),
//     optional chain (`ctx.secrets?.ref(...)`), non-literal `ref(...)` arg.
//     A `true` value tells the UI "the static list is incomplete; treat as
//     advisory." Silent under-reporting is the failure mode we're avoiding.
//
// Both decisions are tested.

function extractCapabilities(sf: ts.SourceFile): ToolCapabilities {
    const names = new Set<string>()
    let dynamic = false

    /** A `ctx.secrets.ref(...)` call with the exact static receiver shape. */
    function isCtxSecretsRefCall(call: ts.CallExpression): boolean {
        const fn = call.expression
        if (!ts.isPropertyAccessExpression(fn)) {
            return false
        }
        // .ref
        if (!ts.isIdentifier(fn.name) || fn.name.text !== 'ref') {
            return false
        }
        // .secrets
        const inner = fn.expression
        if (!ts.isPropertyAccessExpression(inner)) {
            return false
        }
        if (!ts.isIdentifier(inner.name) || inner.name.text !== 'secrets') {
            return false
        }
        // Receiver must be the literal identifier `ctx`. Other identifiers
        // (`client.secrets.ref` from a third-party SDK) would over-collect.
        return ts.isIdentifier(inner.expression) && inner.expression.text === 'ctx'
    }

    /** Any access to `ctx.secrets` (member, element, optional chain) — the
     *  signal that the author touched the secrets surface in a way the
     *  static collector may not have captured. */
    function isCtxSecretsAccess(node: ts.Node): boolean {
        // `ctx.secrets` / `ctx?.secrets`
        if (ts.isPropertyAccessExpression(node)) {
            return (
                ts.isIdentifier(node.expression) &&
                node.expression.text === 'ctx' &&
                ts.isIdentifier(node.name) &&
                node.name.text === 'secrets'
            )
        }
        // `ctx['secrets']` / `ctx?.['secrets']`
        if (ts.isElementAccessExpression(node)) {
            return (
                ts.isIdentifier(node.expression) &&
                node.expression.text === 'ctx' &&
                ts.isStringLiteral(node.argumentExpression) &&
                node.argumentExpression.text === 'secrets'
            )
        }
        return false
    }

    /** Destructure of `ctx`: `const { secrets } = ctx` — author pulled
     *  `secrets` off `ctx` into a local; downstream `.ref` calls are
     *  outside our static collector's receiver shape. */
    function isCtxSecretsDestructure(node: ts.Node): boolean {
        if (!ts.isVariableDeclaration(node)) {
            return false
        }
        if (!node.initializer || !ts.isIdentifier(node.initializer) || node.initializer.text !== 'ctx') {
            return false
        }
        if (!ts.isObjectBindingPattern(node.name)) {
            return false
        }
        for (const el of node.name.elements) {
            // `secrets` or `secrets: <alias>` from the `ctx` object
            const sourceName = el.propertyName ?? el.name
            if (ts.isIdentifier(sourceName) && sourceName.text === 'secrets') {
                return true
            }
        }
        return false
    }

    function visit(node: ts.Node): void {
        if (ts.isCallExpression(node) && isCtxSecretsRefCall(node)) {
            const [arg] = node.arguments
            if (arg && ts.isStringLiteral(arg)) {
                names.add(arg.text)
            } else {
                dynamic = true
            }
        } else if (isCtxSecretsAccess(node)) {
            // Allow the static-call shape to pass without flagging. The
            // `ctx.secrets` in `ctx.secrets.ref(...)` IS a PropertyAccess
            // and would be matched here too — exclude it when its parent
            // is the receiver of a matched static call. Anything else
            // (`ctx.secrets` standalone, `ctx.secrets.foo()`,
            // `ctx['secrets']`, etc.) is an alias / unexpected use → flag.
            const parent = node.parent
            const isStaticRefReceiver =
                parent &&
                ts.isPropertyAccessExpression(parent) &&
                ts.isIdentifier(parent.name) &&
                parent.name.text === 'ref' &&
                parent.parent &&
                ts.isCallExpression(parent.parent) &&
                parent.parent.expression === parent &&
                isCtxSecretsRefCall(parent.parent)
            if (!isStaticRefReceiver) {
                dynamic = true
            }
        } else if (isCtxSecretsDestructure(node)) {
            dynamic = true
        }
        ts.forEachChild(node, visit)
    }

    visit(sf)
    return {
        secret_refs: [...names].sort(),
        dynamic_secret_refs: dynamic,
    }
}
