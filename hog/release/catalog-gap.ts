// Whether the commits since <base> change code compiled into hog that the downloadable tool catalog can't
// deliver. The compiled files come from the build metafiles. Run with --base <commit>, usually the last release
// tag; prints the result as JSON. --list-compiled prints only the compiled files, one per line, for the release
// build, whose sparse checkout has no git history or workflow to compare.

import { execFileSync } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, posix, relative, resolve } from 'node:path'
import { parseArgs } from 'node:util'
import ts from 'typescript'
import { parse as parseYaml } from 'yaml'
import { z } from 'zod'

import { parseJsonOrUndefined } from '../src/core/json'

export const CATALOG_TOOLS_JSON = 'services/mcp/schema/cli-catalog-tools.json'
export const CATALOG_SCHEMA = 'services/mcp/src/cli/catalog/schema.ts'
const RELEASE_WORKFLOW = '.github/workflows/release-hog.yml'
const RELEASE_BUILD_JOB = 'build'
const GLOB_PATHSPEC = ':(glob)'
const HOG_SOURCE_PATHS = 'HOG_SOURCE_PATHS'
const GENERATED_TOOLS_DIR = 'services/mcp/src/tools/generated/'
const GENERATED_REGISTRY = `${GENERATED_TOOLS_DIR}index.ts`
// Generated, but code rather than catalog data: the barrel, the hook registry and the query wrappers.
const GENERATED_CODE = new Set(['index.ts', 'hooks.ts', 'query-wrappers.ts'])
// The zod schemas orval generates from the API. A downloaded catalog entry carries its tool's input schema,
// so a generated tool module only reads them when hog falls back to the tools it was built with.
const GENERATED_SCHEMAS_DIR = 'services/mcp/src/generated/'
const REGISTRY_IMPORT = /^import \{ GENERATED_TOOLS as (\w+) \} from '\.\/([\w-]+)'$/
const REGISTRY_SPREAD = /^\s+\.\.\.(\w+),$/
const ZOD_MODULES = new Set(['zod', 'zod/v4'])
// zod's schema builders, which run none of the callbacks they take. Anything else, like `parse`, can run code.
const ZOD_BUILDERS = new Set([
    'any',
    'array',
    'bigint',
    'boolean',
    'catchall',
    'coerce',
    'date',
    'datetime',
    'default',
    'describe',
    'discriminatedUnion',
    'email',
    'enum',
    'gt',
    'gte',
    'int',
    'intersection',
    'length',
    'literal',
    'looseObject',
    'lt',
    'lte',
    'max',
    'min',
    'multipleOf',
    'nativeEnum',
    'negative',
    'never',
    'nonempty',
    'nonnegative',
    'nonpositive',
    'null',
    'nullable',
    'nullish',
    'number',
    'object',
    'optional',
    'passthrough',
    'positive',
    'record',
    'regex',
    'strict',
    'strictObject',
    'string',
    'tuple',
    'undefined',
    'union',
    'unknown',
    'url',
    'uuid',
])
const TOOL_NAME = /^\s+name: '([a-z0-9-]+)',$/m
const DEFINITION_FILES = new Set([
    'services/mcp/schema/tool-definitions.json',
    'services/mcp/schema/generated-tool-definitions.json',
])

export interface Reason {
    file: string
    why: string
}

export interface GapResult {
    needsRelease: boolean
    bump: 'patch' | 'minor'
    reasons: Reason[]
}

export interface CompiledGraph {
    files: Set<string>
    importers: Map<string, Set<string>>
    // For each compiled file, the specifiers its importers wrote for it, as the build resolved them. A specifier
    // the build can't name, like a dynamic import's, is UNNAMED_IMPORT.
    specifiers?: Map<string, Map<string, string[]>>
}

export const UNNAMED_IMPORT = ''

export interface GapInput {
    changed: string[]
    compiled: CompiledGraph
    readBase: (path: string) => string | undefined
    readHead: (path: string) => string | undefined
    // The tools the built catalog ships. Without it, every tool the catalog tool list names counts as carried.
    carried?: Set<string>
}

const JsonObject = z.record(z.string(), z.unknown())
const Metafile = z.object({
    inputs: z.record(
        z.string(),
        z.object({
            imports: z
                .array(
                    z.object({
                        path: z.string(),
                        kind: z.string().optional(),
                        original: z.string().optional(),
                        external: z.boolean().optional(),
                    })
                )
                .optional(),
        })
    ),
})
const Workflow = z.object({
    env: z.record(z.string(), z.unknown()).optional(),
    jobs: z.record(
        z.string(),
        z.object({
            steps: z.array(
                z.object({ uses: z.string().optional(), with: z.record(z.string(), z.unknown()).optional() })
            ),
        })
    ),
})

function jsonObject(text: string | undefined): Record<string, unknown> {
    return (text && parseJsonOrUndefined(text, JsonObject)) || {}
}

function generatedToolNames(source: string | undefined): string[] {
    const map = source?.split('export const GENERATED_TOOLS')[1] ?? ''
    return [...map.matchAll(/^\s+'([a-z0-9-]+)':/gm)].map((match) => match[1]!)
}

function catalogTools(input: GapInput): Set<string> {
    return input.carried ?? new Set(Object.keys(jsonObject(input.readHead(CATALOG_TOOLS_JSON))))
}

const BuiltCatalog = z.object({ tools: z.array(z.object({ name: z.string() })) })

// The catalog build drops some tools its tool list names, like staff-only ones, which stay compiled into hog.
// So the build itself says what ships, rather than a copy of its rules.
function builtCatalogTools(repoRoot: string): Set<string> {
    const folder = mkdtempSync(join(tmpdir(), 'hog-catalog-'))
    try {
        const out = join(folder, 'cli-catalog.json')
        execFileSync('pnpm', ['--filter', '@posthog/mcp', 'run', 'build:cli:catalog', out], {
            cwd: repoRoot,
            stdio: ['ignore', 'ignore', 'inherit'],
        })
        const catalog = parseJsonOrUndefined(readFileSync(out, 'utf8'), BuiltCatalog)
        if (!catalog) {
            throw new Error(`The catalog build wrote no catalog to ${out}.`)
        }
        return new Set(catalog.tools.map((tool) => tool.name))
    } finally {
        rmSync(folder, { recursive: true, force: true })
    }
}

function changedKeys(base: string | undefined, head: string | undefined): string[] {
    const before = jsonObject(base)
    const after = jsonObject(head)
    return [...new Set([...Object.keys(before), ...Object.keys(after)])].filter(
        (key) => JSON.stringify(before[key]) !== JSON.stringify(after[key])
    )
}

function schemaVersion(source: string | undefined): string | undefined {
    return source?.match(/export const CATALOG_SCHEMA_VERSION = (\d+)/)?.[1]
}

function generatedModuleName(file: string): string | undefined {
    const name = file.startsWith(GENERATED_TOOLS_DIR) ? file.slice(GENERATED_TOOLS_DIR.length) : undefined
    return name && !name.includes('/') && !GENERATED_CODE.has(name) ? name : undefined
}

// Undefined when the module defines no tools, which proves nothing.
function uncarriedTools(input: GapInput, carried: Set<string>, file: string): string[] | undefined {
    const tools = new Set([...generatedToolNames(input.readBase(file)), ...generatedToolNames(input.readHead(file))])
    return tools.size > 0 ? [...tools].filter((tool) => !carried.has(tool)) : undefined
}

const printer = ts.createPrinter({ removeComments: true })

interface Scope {
    zod: Set<string>
    globalRegExp: boolean
}

// The names a top-level statement binds. Undefined stands for a binding this can't name, like a destructured one.
function declaredNames(statement: ts.Statement): (string | undefined)[] {
    if (ts.isImportDeclaration(statement)) {
        const clause = statement.importClause
        const bindings = clause?.namedBindings
        return [
            ...(clause?.name ? [clause.name.text] : []),
            ...(bindings && ts.isNamespaceImport(bindings) ? [bindings.name.text] : []),
            ...(bindings && ts.isNamedImports(bindings) ? bindings.elements.map((element) => element.name.text) : []),
        ]
    }
    if (ts.isVariableStatement(statement)) {
        return statement.declarationList.declarations.map((declaration) =>
            ts.isIdentifier(declaration.name) ? declaration.name.text : undefined
        )
    }
    if (ts.isFunctionDeclaration(statement) || ts.isClassDeclaration(statement) || ts.isEnumDeclaration(statement)) {
        return [statement.name?.text]
    }
    return []
}

function moduleScope(file: ts.SourceFile): Scope {
    const zod = new Set<string>()
    let globalRegExp = true
    for (const statement of file.statements) {
        if (ts.isImportDeclaration(statement)) {
            const bindings = statement.importClause?.namedBindings
            const fromZod =
                ts.isStringLiteral(statement.moduleSpecifier) && ZOD_MODULES.has(statement.moduleSpecifier.text)
            if (fromZod && bindings && ts.isNamespaceImport(bindings)) {
                zod.add(bindings.name.text)
            }
            if (fromZod && bindings && ts.isNamedImports(bindings)) {
                bindings.elements
                    .filter((element) => (element.propertyName ?? element.name).text === 'z')
                    .forEach((element) => zod.add(element.name.text))
            }
        }
        if (declaredNames(statement).some((name) => name === 'RegExp' || name === undefined)) {
            globalRegExp = false
        }
    }
    return { zod, globalRegExp }
}

// Whether evaluating the expression when hog imports the module runs no code beyond building literals,
// functions, regular expressions and zod schemas.
function inertExpression(node: ts.Expression, scope: Scope): boolean {
    if (
        ts.isParenthesizedExpression(node) ||
        ts.isAsExpression(node) ||
        ts.isSatisfiesExpression(node) ||
        ts.isNonNullExpression(node)
    ) {
        return inertExpression(node.expression, scope)
    }
    if (
        ts.isArrowFunction(node) ||
        ts.isFunctionExpression(node) ||
        ts.isLiteralExpression(node) ||
        ts.isIdentifier(node)
    ) {
        return true
    }
    if (
        node.kind === ts.SyntaxKind.TrueKeyword ||
        node.kind === ts.SyntaxKind.FalseKeyword ||
        node.kind === ts.SyntaxKind.NullKeyword
    ) {
        return true
    }
    if (ts.isPrefixUnaryExpression(node)) {
        return node.operator === ts.SyntaxKind.MinusToken && ts.isNumericLiteral(node.operand)
    }
    if (ts.isArrayLiteralExpression(node)) {
        return node.elements.every((element) => !ts.isSpreadElement(element) && inertExpression(element, scope))
    }
    if (ts.isObjectLiteralExpression(node)) {
        return node.properties.every(
            (property) =>
                (ts.isPropertyAssignment(property) &&
                    !ts.isComputedPropertyName(property.name) &&
                    inertExpression(property.initializer, scope)) ||
                (ts.isShorthandPropertyAssignment(property) && !property.objectAssignmentInitializer)
        )
    }
    if (ts.isNewExpression(node)) {
        return (
            scope.globalRegExp &&
            ts.isIdentifier(node.expression) &&
            node.expression.text === 'RegExp' &&
            (node.arguments ?? []).every((argument) => ts.isStringLiteralLike(argument))
        )
    }
    if (ts.isCallExpression(node)) {
        return (
            !node.questionDotToken &&
            zodBuilder(node.expression, scope) &&
            node.arguments.every((argument) => inertExpression(argument, scope))
        )
    }
    return ts.isPropertyAccessExpression(node) && zodBuilder(node, scope)
}

function zodBuilder(node: ts.Expression, scope: Scope): boolean {
    if (ts.isIdentifier(node)) {
        return scope.zod.has(node.text)
    }
    if (ts.isPropertyAccessExpression(node)) {
        return !node.questionDotToken && ZOD_BUILDERS.has(node.name.text) && zodBuilder(node.expression, scope)
    }
    return ts.isCallExpression(node) && inertExpression(node, scope)
}

// The name a top-level statement declares when evaluating it at import runs nothing, as for the generator's
// `export const X = () => zod.object(...)`. Undefined for any other statement.
function inertDeclaration(statement: ts.Statement, scope: Scope): string | undefined {
    if (ts.isFunctionDeclaration(statement)) {
        return statement.body && statement.name?.text
    }
    if (!ts.isVariableStatement(statement) || !(statement.declarationList.flags & ts.NodeFlags.Const)) {
        return undefined
    }
    const [declaration, ...others] = statement.declarationList.declarations
    return declaration &&
        others.length === 0 &&
        ts.isIdentifier(declaration.name) &&
        declaration.initializer &&
        inertExpression(declaration.initializer, scope)
        ? declaration.name.text
        : undefined
}

interface Block {
    // As written, for reading tool names and schema references.
    text: string
    // As compiled, without comments, for comparing.
    code: string
}

// Splits a module into the declarations hog can import without running anything, and the prelude: every other
// top-level statement, such as imports and calls. The prelude runs whenever hog imports the module, so a change
// to it counts as a change to everything.
function topLevelBlocks(source: string): { prelude: string; blocks: Map<string, Block> } {
    const file = ts.createSourceFile('module.ts', source, ts.ScriptTarget.Latest, true)
    const scope = moduleScope(file)
    const prelude: string[] = []
    const blocks = new Map<string, Block>()
    for (const statement of file.statements) {
        const code = printer.printNode(ts.EmitHint.Unspecified, statement, file)
        const name = inertDeclaration(statement, scope)
        if (name && !blocks.has(name)) {
            blocks.set(name, { text: statement.getText(file), code })
        } else {
            prelude.push(code)
        }
    }
    return { prelude: prelude.join('\n'), blocks }
}

// Whether every top-level statement of the module runs nothing when hog imports it, apart from importing types
// and zod.
function inertModule(source: string | undefined): boolean {
    const file = ts.createSourceFile('module.ts', source ?? '', ts.ScriptTarget.Latest, true)
    const scope = moduleScope(file)
    return file.statements.every(
        (statement) =>
            (ts.isImportDeclaration(statement) &&
                ts.isStringLiteral(statement.moduleSpecifier) &&
                (statement.importClause?.isTypeOnly || ZOD_MODULES.has(statement.moduleSpecifier.text))) ||
            inertDeclaration(statement, scope) !== undefined
    )
}

function referencesAny(text: string, names: Iterable<string>): boolean {
    return [...names].some((name) => new RegExp(`\\b${name}\\b`).test(text))
}

// Undefined when the change reaches beyond the blocks, which leaves every schema suspect.
function alteredSchemas(input: GapInput, file: string): Set<string> | undefined {
    const base = topLevelBlocks(input.readBase(file) ?? '')
    const head = topLevelBlocks(input.readHead(file) ?? '')
    if (base.prelude !== head.prelude) {
        return undefined
    }

    const altered = new Set(
        [...new Set([...base.blocks.keys(), ...head.blocks.keys()])].filter(
            (name) => base.blocks.get(name)?.code !== head.blocks.get(name)?.code
        )
    )
    let grew = true
    while (grew) {
        grew = false
        for (const [name, { code }] of head.blocks) {
            if (!altered.has(name) && referencesAny(code, altered)) {
                altered.add(name)
                grew = true
            }
        }
    }
    return altered
}

// Undefined when a tool the module registers can't be traced, so every tool counts.
function schemasByTool(source: string | undefined): Map<string, Set<string>> | undefined {
    if (!source) {
        return undefined
    }
    const { blocks } = topLevelBlocks(source)
    const schemasOf = (name: string, seen: Set<string>): Set<string> => {
        const text = blocks.get(name)?.text ?? ''
        const schemas = new Set([...text.matchAll(/orvalSchemas\.(\w+)/g)].map((match) => match[1]!))
        for (const other of blocks.keys()) {
            if (other !== name && !seen.has(other) && referencesAny(text, [other])) {
                seen.add(other)
                schemasOf(other, seen).forEach((schema) => schemas.add(schema))
            }
        }
        return schemas
    }

    const byTool = new Map<string, Set<string>>()
    for (const [name, { text }] of blocks) {
        const tool = text.match(TOOL_NAME)?.[1]
        if (tool) {
            byTool.set(tool, schemasOf(name, new Set([name, 'GENERATED_TOOLS'])))
        }
    }
    return generatedToolNames(source).every((tool) => byTool.has(tool)) ? byTool : undefined
}

// The values a module imports from a schema file by name, as the TypeScript parser reads them, so escapes and
// comments read as they compile. The build resolved which specifiers name the file. Undefined, so every schema
// counts as read, when the module reads the file any other way, such as a namespace or default import, a
// re-export, `import()` or `require`, or through a specifier no import declaration accounts for.
function namedImports(source: string | undefined, specifiers: string[] | undefined): Set<string> | undefined {
    if (!specifiers?.length || specifiers.includes(UNNAMED_IMPORT)) {
        return undefined
    }
    const wanted = new Set(specifiers)
    const file = ts.createSourceFile('importer.ts', source ?? '', ts.ScriptTarget.Latest, true)
    const names = new Set<string>()
    const declared = new Set<ts.Node>()

    for (const statement of file.statements) {
        if (
            !ts.isImportDeclaration(statement) ||
            !ts.isStringLiteral(statement.moduleSpecifier) ||
            !wanted.has(statement.moduleSpecifier.text)
        ) {
            continue
        }
        declared.add(statement.moduleSpecifier)
        const clause = statement.importClause
        if (clause?.isTypeOnly) {
            continue
        }
        if (!clause || clause.name || !clause.namedBindings || !ts.isNamedImports(clause.namedBindings)) {
            return undefined
        }
        for (const element of clause.namedBindings.elements) {
            if (!element.isTypeOnly) {
                names.add((element.propertyName ?? element.name).text)
            }
        }
    }

    const accounted = new Set([...declared].map((node) => (node as ts.StringLiteral).text))
    let undeclared = [...wanted].some((specifier) => !accounted.has(specifier))
    const visit = (node: ts.Node): void => {
        if (ts.isStringLiteralLike(node) && wanted.has(node.text) && !declared.has(node)) {
            undeclared = true
        }
        ts.forEachChild(node, visit)
    }
    visit(file)
    return undeclared ? undefined : names
}

// Code other than the registry that imports a generated module, like an alias that wraps its tools. hog runs that
// code whatever the catalog carries.
function handWrittenImporters(input: GapInput, module: string): string[] {
    return [...(input.compiled.importers.get(module) ?? [])].filter((importer) => importer !== GENERATED_REGISTRY)
}

// The importers of a changed schema file that hog runs differently with a downloaded catalog. A generated
// tool module counts only through tools that read an altered schema and that the catalog doesn't carry,
// because hog builds every tool the catalog carries from the catalog entry. A change outside the schemas runs
// whenever hog imports the file, so every importer counts.
function schemaChangeBlockers(input: GapInput, carried: Set<string>, file: string): string[] {
    const importers = [...(input.compiled.importers.get(file) ?? [])]
    if (importers.length === 0) {
        return ['no importer found']
    }
    const altered = alteredSchemas(input, file)
    if (!altered) {
        return importers
    }

    return importers.filter((importer) => {
        if (generatedModuleName(importer)) {
            const byTool = schemasByTool(input.readHead(importer))
            const affected = byTool
                ? [...byTool]
                      .filter(([, schemas]) => [...schemas].some((schema) => altered.has(schema)))
                      .map(([tool]) => tool)
                : generatedToolNames(input.readHead(importer))
            return (
                affected.some((tool) => !carried.has(tool)) ||
                (affected.length > 0 && handWrittenImporters(input, importer).length > 0)
            )
        }
        const named = namedImports(input.readHead(importer), input.compiled.specifiers?.get(file)?.get(importer))
        return !named || [...named].some((name) => altered.has(name))
    })
}

interface Registrations {
    modules: Map<string, string>
    spread: Set<string>
    rest: string
}

function registrations(source: string | undefined): Registrations {
    const modules = new Map<string, string>()
    const spread = new Set<string>()
    const rest: string[] = []
    for (const line of (source ?? '').split('\n')) {
        const imported = line.match(REGISTRY_IMPORT)
        const spreadAlias = line.match(REGISTRY_SPREAD)?.[1]
        if (imported) {
            modules.set(imported[1]!, `${GENERATED_TOOLS_DIR}${imported[2]!}.ts`)
        } else if (spreadAlias) {
            spread.add(spreadAlias)
        } else {
            rest.push(line)
        }
    }
    return { modules, spread, rest: rest.join('\n') }
}

// The registry lists the generated modules hog falls back to when the catalog lacks a tool. A change that only
// imports, spreads or drops modules whose tools the catalog carries changes nothing hog runs with a downloaded
// catalog. Any other line that changes counts.
function registryChangeDelivered(input: GapInput, carried: Set<string>): boolean {
    const base = registrations(input.readBase(GENERATED_REGISTRY))
    const head = registrations(input.readHead(GENERATED_REGISTRY))
    if (base.rest !== head.rest) {
        return false
    }

    const carriedAt = (read: (path: string) => string | undefined, path: string | undefined): boolean => {
        const tools = generatedToolNames(path ? read(path) : undefined)
        return (
            path === undefined ||
            (generatedModuleName(path) !== undefined &&
                inertModule(read(path)) &&
                tools.length > 0 &&
                tools.every((tool) => carried.has(tool)))
        )
    }
    const entry = (side: Registrations, alias: string): string =>
        `${side.modules.get(alias) ?? ''} ${side.spread.has(alias)}`
    const aliases = new Set([...base.modules.keys(), ...base.spread, ...head.modules.keys(), ...head.spread])
    return [...aliases]
        .filter((alias) => entry(base, alias) !== entry(head, alias))
        .every(
            (alias) =>
                (base.modules.has(alias) || head.modules.has(alias)) &&
                carriedAt(input.readBase, base.modules.get(alias)) &&
                carriedAt(input.readHead, head.modules.get(alias))
        )
}

// Anything compiled into hog counts unless the catalog provably carries it.
export function findCatalogGaps(input: GapInput): GapResult {
    const carried = catalogTools(input)
    const reasons: Reason[] = []

    for (const file of input.changed) {
        if (!input.compiled.files.has(file) || file === CATALOG_TOOLS_JSON) {
            continue
        }

        if (generatedModuleName(file)) {
            if (
                topLevelBlocks(input.readBase(file) ?? '').prelude !==
                topLevelBlocks(input.readHead(file) ?? '').prelude
            ) {
                reasons.push({ file, why: 'top-level code that runs whenever hog loads the module' })
                continue
            }
            const missing = uncarriedTools(input, carried, file)
            const wrappers = handWrittenImporters(input, file)
            if (missing?.length === 0 && wrappers.length === 0) {
                continue
            }
            if (missing?.length === 0) {
                reasons.push({ file, why: `generated tools that hand-written code wraps: ${wrappers.join(', ')}` })
                continue
            }
            reasons.push({
                file,
                why: `generated tools the catalog doesn't carry: ${missing?.join(', ') || 'none found'}`,
            })
            continue
        }

        if (file.startsWith(GENERATED_SCHEMAS_DIR)) {
            const blockers = schemaChangeBlockers(input, carried, file)
            if (blockers.length === 0) {
                continue
            }
            reasons.push({
                file,
                why: `generated schemas read by code the catalog can't deliver: ${blockers.join(', ')}`,
            })
            continue
        }

        if (file === GENERATED_REGISTRY) {
            if (registryChangeDelivered(input, carried)) {
                continue
            }
            reasons.push({ file, why: 'the generated tool registry changed beyond modules the catalog carries' })
            continue
        }

        if (DEFINITION_FILES.has(file)) {
            const keys = changedKeys(input.readBase(file), input.readHead(file))
            const missing = keys.filter((key) => !carried.has(key))
            if (missing.length === 0) {
                continue
            }
            reasons.push({ file, why: `definitions of tools the catalog doesn't carry: ${missing.join(', ')}` })
            continue
        }

        reasons.push({ file, why: 'compiled into hog' })
    }

    const formatChanged =
        schemaVersion(input.readBase(CATALOG_SCHEMA)) !== schemaVersion(input.readHead(CATALOG_SCHEMA))
    if (formatChanged && !reasons.some((reason) => reason.file === CATALOG_SCHEMA)) {
        reasons.push({ file: CATALOG_SCHEMA, why: 'the catalog format version changed' })
    }

    return { needsRelease: reasons.length > 0, bump: formatChanged ? 'minor' : 'patch', reasons }
}

export function compiledFiles(metafiles: { path: string; root: string }[], repoRoot: string): CompiledGraph {
    const files = new Set<string>()
    const importers = new Map<string, Set<string>>()
    const specifiers = new Map<string, Map<string, string[]>>()
    // A module a build plugin makes up, like `cf-stub:cloudflare:workers`, is no file in the repository.
    const repoFile = (root: string, path: string): string | undefined => {
        if (path.includes(':') && !existsSync(resolve(root, path))) {
            return undefined
        }
        const file = relative(repoRoot, resolve(root, path)).split('\\').join(posix.sep)
        return file.startsWith('..') || file.includes('node_modules/') || file.startsWith('services/mcp/dist/')
            ? undefined
            : file
    }

    for (const { path, root } of metafiles) {
        const inputs = existsSync(path) ? parseJsonOrUndefined(readFileSync(path, 'utf8'), Metafile)?.inputs : undefined
        if (!inputs || Object.keys(inputs).length === 0) {
            throw new Error(
                `${path} is not a build metafile that lists its inputs. Build hog and the CLI library first.`
            )
        }
        for (const [input, { imports }] of Object.entries(inputs)) {
            const file = repoFile(root, input)
            if (!file) {
                continue
            }
            files.add(file)
            for (const imported of imports ?? []) {
                const target = imported.external ? undefined : repoFile(root, imported.path)
                if (target) {
                    importers.set(target, (importers.get(target) ?? new Set()).add(file))
                    const byImporter = specifiers.get(target) ?? new Map<string, string[]>()
                    const named = imported.kind === 'import-statement' ? imported.original : undefined
                    byImporter.set(file, [...(byImporter.get(file) ?? []), named ?? UNNAMED_IMPORT])
                    specifiers.set(target, byImporter)
                }
            }
        }
    }
    return { files, importers, specifiers }
}

// The workflow passes HOG_SOURCE_PATHS to the approver check as extra paths, so they must cover everything the
// release builds from.
export function hogSourcePaths(workflow: string): string[] {
    const sources = String(Workflow.parse(parseYaml(workflow)).env?.[HOG_SOURCE_PATHS] ?? '')
        .split(/\s+/)
        .filter(Boolean)
    if (sources.length === 0) {
        throw new Error(`${RELEASE_WORKFLOW} sets no ${HOG_SOURCE_PATHS} to check.`)
    }
    return sources
}

// The release build's inputs that a path names: what its sparse checkout names without a wildcard, the workflow's
// HOG_SOURCE_PATHS, the local actions the workflow runs, and the workflow itself.
export function releaseBuildInputs(workflow: string): string[] {
    const parsed = Workflow.parse(parseYaml(workflow))
    const named = releaseCheckoutPatterns(workflow)
        .filter((pattern) => !pattern.startsWith('!') && !pattern.includes('*'))
        .map((pattern) => pattern.replace(/^\//, '').replace(/\/$/, ''))
    const sources = hogSourcePaths(workflow)
    const actions = Object.values(parsed.jobs)
        .flatMap((job) => job.steps)
        .flatMap((step) => (step.uses?.startsWith('./') ? [step.uses.slice(2)] : []))
    return [...new Set([...named, ...sources, ...actions, RELEASE_WORKFLOW])]
}

// The paths check-approvers.sh doesn't count, given the git pathspecs it prints with --list-paths: a plain path
// covers itself and everything under it, and `:(glob)` matches as a glob. A path may name a folder, which a glob
// covers when it matches what the folder holds.
export function outsideReleasePaths(files: string[], releasePaths: string[]): string[] {
    const covers = (path: string, file: string): boolean =>
        path.startsWith(GLOB_PATHSPEC)
            ? [file, `${file}/file`].some((candidate) =>
                  new Bun.Glob(path.slice(GLOB_PATHSPEC.length)).match(candidate)
              )
            : file === path || file.startsWith(`${path}/`)
    return files.filter((file) => !releasePaths.some((path) => covers(path, file)))
}

export function releaseCheckoutPatterns(workflow: string): string[] {
    const steps = Workflow.parse(parseYaml(workflow)).jobs[RELEASE_BUILD_JOB]?.steps ?? []
    const sparse = steps.find((step) => step.uses?.startsWith('actions/checkout@'))?.with?.['sparse-checkout']
    if (typeof sparse !== 'string') {
        throw new Error(`The ${RELEASE_BUILD_JOB} job of ${RELEASE_WORKFLOW} has no sparse checkout to check.`)
    }
    return sparse
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
}

// The patterns are git's non-cone sparse-checkout patterns, and the release build's are all anchored. A
// pattern matches a path or any folder above it, `name/` matches only folders, and the last matching pattern
// decides, so `!/*/` can drop every top-level folder that an earlier `/*` took in.
export function outsideCheckout(compiled: Set<string>, patterns: string[]): string[] {
    const rules = patterns.map((pattern) => {
        const negated = pattern.startsWith('!')
        const body = negated ? pattern.slice(1) : pattern
        if (!body.startsWith('/')) {
            throw new Error(`Only anchored sparse-checkout patterns are supported, not ${pattern}.`)
        }
        const folderOnly = body.endsWith('/')
        return { negated, folderOnly, glob: new Bun.Glob(body.slice(1, folderOnly ? -1 : undefined)) }
    })

    return [...compiled].filter((file) => {
        const parts = file.split('/')
        const folders = parts.slice(0, -1).map((_, index) => parts.slice(0, index + 1).join('/'))
        const included = rules.reduce((current, rule) => {
            const candidates = rule.folderOnly ? folders : [...folders, file]
            return candidates.some((candidate) => rule.glob.match(candidate)) ? !rule.negated : current
        }, false)
        return !included
    })
}

// Generated schema files are larger than execFileSync's default 1 MiB output buffer.
const GIT_OUTPUT_LIMIT = 512 * 1024 * 1024

// Only a path the commit lacks reads as missing. Any other git failure throws, so it can't hide a change.
export function readAt(repoRoot: string): (ref: string) => (path: string) => string | undefined {
    return (ref) => (path) =>
        git(repoRoot, 'ls-tree', ref, '--', path).trim() ? git(repoRoot, 'show', `${ref}:${path}`) : undefined
}

function git(repoRoot: string, ...args: string[]): string {
    return execFileSync('git', args, {
        cwd: repoRoot,
        encoding: 'utf8',
        maxBuffer: GIT_OUTPUT_LIMIT,
        stdio: ['ignore', 'pipe', 'pipe'],
    })
}

if (import.meta.main) {
    const repoRoot = resolve(import.meta.dir, '../..')
    const { values } = parseArgs({
        options: {
            base: { type: 'string' },
            'list-compiled': { type: 'boolean', default: false },
            // What `check-approvers.sh --list-paths` prints for the checker the release will run.
            'release-paths': { type: 'string' },
            'hog-metafile': { type: 'string', default: resolve(repoRoot, 'hog/dist/hog.metafile.json') },
            'mcp-metafile': {
                type: 'string',
                multiple: true,
                default: [
                    resolve(repoRoot, 'services/mcp/dist/cli-library.metafile.json'),
                    resolve(repoRoot, 'services/mcp/dist/cli-skills.metafile.json'),
                ],
            },
        },
    })
    if (!values.base && !values['list-compiled']) {
        console.error('Pass the commit to compare with, usually the last release tag, with --base.')
        process.exit(1)
    }

    const metafiles = [
        { path: values['hog-metafile'], root: resolve(repoRoot, 'hog') },
        ...values['mcp-metafile'].map((path) => ({ path, root: resolve(repoRoot, 'services/mcp') })),
    ]
    let compiled: CompiledGraph
    try {
        compiled = compiledFiles(metafiles, repoRoot)
    } catch (error) {
        console.error(error instanceof Error ? error.message : String(error))
        process.exit(1)
    }

    if (values['list-compiled'] || !values.base) {
        process.stdout.write(
            [...compiled.files]
                .sort()
                .map((file) => `${file}\n`)
                .join('')
        )
        process.exit(0)
    }

    const read = readAt(repoRoot)
    const result = findCatalogGaps({
        changed: git(repoRoot, 'diff', '--name-only', `${values.base}...HEAD`).split('\n').filter(Boolean),
        compiled,
        readBase: read(values.base),
        readHead: read('HEAD'),
        carried: builtCatalogTools(repoRoot),
    })
    const patterns = releaseCheckoutPatterns(readFileSync(resolve(repoRoot, RELEASE_WORKFLOW), 'utf8'))
    const releasePaths = values['release-paths']
        ? readFileSync(values['release-paths'], 'utf8').split('\n').filter(Boolean)
        : undefined
    const releaseWorkflow = readFileSync(resolve(repoRoot, RELEASE_WORKFLOW), 'utf8')
    const buildsFrom = [...compiled.files, ...releaseBuildInputs(releaseWorkflow)]
    process.stdout.write(
        `${JSON.stringify({
            ...result,
            outsideReleaseCheckout: outsideCheckout(compiled.files, patterns),
            outsideSourcePaths: outsideReleasePaths(buildsFrom, hogSourcePaths(releaseWorkflow)),
            ...(releasePaths && { outsideReleasePaths: outsideReleasePaths(buildsFrom, releasePaths) }),
        })}\n`
    )
}
