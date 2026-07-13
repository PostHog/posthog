/**
 * Code-execution MCP artifacts emitter — runs as the final pass of
 * `scripts/generate.ts`, after the SDK sources are emitted and formatted.
 *
 * Inputs (committed files only — no network, no Django):
 *   - packages/sdk/src/generated/*.ts        (the just-emitted SDK surface)
 *   - packages/sdk/src/core/{config,query}.ts (RequestOptions, QueryBase.run)
 *   - services/mcp/schema/generated-tool-definitions.json (curated metadata)
 *   - packages/sdk/dist/index.d.ts           (tsup dts rollup, built here)
 *
 * Outputs (committed) under services/mcp/src/generated/code-exec/:
 *   - discovery-index.json  (every SDK method + the type declarations reachable
 *     from any signature — backs the `exec types` verbs)
 *   - classifier-table.json (per-operation read/write classification — backs
 *     the plan/apply mutation classifier)
 *   - sdk-dts.ts            (bundled @posthog/sdk .d.ts — compile-gate input)
 *
 * Determinism contract: methods sorted by id, types by name, operations by id;
 * fixed JSON key order; oxfmt applied so committed bytes survive lint-staged.
 */
import { spawnSync } from 'node:child_process'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const SDK_ROOT = path.resolve(__dirname, '..')
const REPO_ROOT = path.resolve(SDK_ROOT, '../..')
const GEN_DIR = path.join(SDK_ROOT, 'src/generated')
const CORE_DIR = path.join(SDK_ROOT, 'src/core')
const OUT_DIR = path.join(REPO_ROOT, 'services/mcp/src/generated/code-exec')
const TOOL_DEFS_PATH = path.join(REPO_ROOT, 'services/mcp/schema/generated-tool-definitions.json')
const DTS_PATH = path.join(SDK_ROOT, 'dist/index.d.ts')

// ---------------------------------------------------------------------------
// Model handed over by generate.ts
// ---------------------------------------------------------------------------

export interface CodeExecMethodModel {
    /** Client property name, e.g. 'featureFlags'. */
    resource: string
    /** Method name on the resource, e.g. 'update'. */
    method: string
    /** Originating MCP tool name. */
    toolName: string
    /** True for `createQueryWrapper` methods (they all POST to /query/). */
    isWrapper: boolean
    /** HTTP method — null for query wrappers. */
    httpMethod: string | null
    /** Transformed request-arg object source (path template + body) — null for wrappers. */
    requestArgText: string | null
}

export interface CodeExecSummary {
    methods: number
    types: number
    operations: number
    dtsBytes: number
}

interface ToolDefinition {
    description?: string
    category?: string
    summary?: string
    title?: string
    required_scopes?: string[]
    annotations?: {
        destructiveHint?: boolean
        readOnlyHint?: boolean
    }
}

// ---------------------------------------------------------------------------
// Type tables: name → declaration, per source space
// ---------------------------------------------------------------------------
//
// The generated SDK has four self-contained type "spaces" that can reuse the
// same bare name for different declarations (e.g. `AIEventType` exists in both
// the vendored `Schemas` namespace and query-responses.ts). References inside
// each module only ever resolve within that module, so the tables are keyed by
// (space, name) and flattened to unique output names at the end.

type TypeSpace = 'inputs' | 'queryResponses' | 'schemas' | 'core'

interface TypeDecl {
    space: TypeSpace
    name: string
    /** Exact declaration source text incl. JSDoc, namespace indentation stripped. */
    declaration: string
    /** Direct references, bare names resolving within the same space. */
    refs: string[]
    /** Property name → type text, for interfaces / object type aliases. */
    props: Map<string, string> | null
}

type TypeTables = Map<TypeSpace, Map<string, TypeDecl>>

/** Generic-parameter-style builtins that never resolve to a table entry. */
const BUILTIN_TYPE_NAMES = new Set([
    'Array',
    'Date',
    'Map',
    'Omit',
    'Partial',
    'Pick',
    'Promise',
    'Readonly',
    'Record',
    'Required',
    'Set',
])

/** Code-unit string comparison — locale-independent, unlike localeCompare. */
function compareStrings(a: string, b: string): number {
    return a < b ? -1 : a > b ? 1 : 0
}

function readSource(filePath: string): ts.SourceFile {
    return ts.createSourceFile(filePath, fs.readFileSync(filePath, 'utf8'), ts.ScriptTarget.Latest, true)
}

/** Declaration text including its JSDoc comment. */
function declText(sf: ts.SourceFile, node: ts.Node): string {
    return sf.getFullText().slice(node.getStart(sf, true), node.getEnd())
}

/** The JSDoc description of a node, collapsed to one line ('' when absent). */
function jsdocDescription(sf: ts.SourceFile, node: ts.Node): string {
    const match = /^\/\*\*([\s\S]*?)\*\//.exec(declText(sf, node))
    if (!match) {
        return ''
    }
    return match[1]!
        .split('\n')
        .map((line) => line.replace(/^\s*\*? ?/, ''))
        .join(' ')
        .replace(/\s+/g, ' ')
        .trim()
}

/** Collect bare type-reference names inside a declaration (heritage, typeof, refs). */
function collectDeclRefs(node: ts.Node, out: Set<string>): void {
    if (ts.isTypeReferenceNode(node) && ts.isIdentifier(node.typeName)) {
        out.add(node.typeName.text)
    }
    if (ts.isTypeQueryNode(node) && ts.isIdentifier(node.exprName)) {
        out.add(node.exprName.text)
    }
    if (ts.isExpressionWithTypeArguments(node) && ts.isIdentifier(node.expression)) {
        out.add(node.expression.text)
    }
    node.forEachChild((child) => collectDeclRefs(child, out))
}

function propName(name: ts.PropertyName): string | null {
    if (ts.isIdentifier(name) || ts.isStringLiteral(name)) {
        return name.text
    }
    return null
}

/** Property map for interfaces and object-literal type aliases (else null). */
function collectProps(node: ts.Node, sf: ts.SourceFile): Map<string, string> | null {
    let membersNode: ts.Node | null = null
    if (ts.isInterfaceDeclaration(node)) {
        membersNode = node
    } else if (ts.isTypeAliasDeclaration(node) && ts.isTypeLiteralNode(node.type)) {
        membersNode = node.type
    }
    if (!membersNode) {
        return null
    }
    const props = new Map<string, string>()
    const members = ts.isInterfaceDeclaration(membersNode)
        ? membersNode.members
        : (membersNode as ts.TypeLiteralNode).members
    for (const member of members) {
        if (ts.isPropertySignature(member) && member.name && member.type) {
            const name = propName(member.name)
            if (name) {
                props.set(name, member.type.getText(sf))
            }
        }
    }
    return props
}

function addDecl(table: Map<string, TypeDecl>, space: TypeSpace, sf: ts.SourceFile, node: ts.Node, name: string): void {
    const text = declText(sf, node)
    const refs = new Set<string>()
    collectDeclRefs(node, refs)
    const existing = table.get(name)
    if (existing) {
        // Enum pattern: `export type X = (typeof X)[...]` + `export const X = {...}`.
        // Merge into one entry so the declaration is self-explanatory.
        existing.declaration = `${existing.declaration}\n\n${text}`
        for (const ref of refs) {
            if (!existing.refs.includes(ref)) {
                existing.refs.push(ref)
            }
        }
        existing.props ??= collectProps(node, sf)
        return
    }
    table.set(name, { space, name, declaration: text, refs: [...refs], props: collectProps(node, sf) })
}

/** Top-level `export interface|type` declarations of a module. */
function parseTopLevelTypes(filePath: string, space: TypeSpace): Map<string, TypeDecl> {
    const sf = readSource(filePath)
    const table = new Map<string, TypeDecl>()
    for (const stmt of sf.statements) {
        if (ts.isInterfaceDeclaration(stmt) || ts.isTypeAliasDeclaration(stmt)) {
            addDecl(table, space, sf, stmt, stmt.name.text)
        }
    }
    finalizeRefs(table)
    return table
}

/** Members of the vendored `namespace Schemas`, dedented one level. */
function parseSchemasNamespace(filePath: string): Map<string, TypeDecl> {
    const sf = readSource(filePath)
    const table = new Map<string, TypeDecl>()
    const nsBody = findSchemasNamespaceBody(sf)
    for (const stmt of nsBody.statements) {
        if (ts.isInterfaceDeclaration(stmt) || ts.isTypeAliasDeclaration(stmt)) {
            addDecl(table, 'schemas', sf, stmt, stmt.name.text)
        } else if (ts.isVariableStatement(stmt)) {
            for (const decl of stmt.declarationList.declarations) {
                if (ts.isIdentifier(decl.name)) {
                    addDecl(table, 'schemas', sf, stmt, decl.name.text)
                }
            }
        }
    }
    // Namespace members carry one level of indentation — strip it so the
    // declarations read as standalone (unqualified) type declarations.
    for (const decl of table.values()) {
        decl.declaration = decl.declaration
            .split('\n')
            .map((line) => (line.startsWith('    ') ? line.slice(4) : line))
            .join('\n')
    }
    finalizeRefs(table)
    return table
}

function findSchemasNamespaceBody(sf: ts.SourceFile): ts.ModuleBlock {
    for (const stmt of sf.statements) {
        if (ts.isModuleDeclaration(stmt) && stmt.name.getText(sf) === 'Schemas' && stmt.body) {
            if (ts.isModuleBlock(stmt.body)) {
                return stmt.body
            }
        }
    }
    throw new Error(`No 'Schemas' namespace found in ${sf.fileName}`)
}

/** Named declarations pulled from the handwritten core (signature-reachable only). */
function parseCoreTypes(): Map<string, TypeDecl> {
    const table = new Map<string, TypeDecl>()
    const wanted: Array<[string, string[]]> = [
        [path.join(CORE_DIR, 'config.ts'), ['RequestOptions']],
        [path.join(CORE_DIR, 'query.ts'), ['QueryNode', 'QueryResponse']],
    ]
    for (const [filePath, names] of wanted) {
        const sf = readSource(filePath)
        for (const stmt of sf.statements) {
            if ((ts.isInterfaceDeclaration(stmt) || ts.isTypeAliasDeclaration(stmt)) && names.includes(stmt.name.text)) {
                addDecl(table, 'core', sf, stmt, stmt.name.text)
            }
        }
    }
    finalizeRefs(table)
    return table
}

/** Restrict each entry's refs to names actually declared in its own space. */
function finalizeRefs(table: Map<string, TypeDecl>): void {
    for (const decl of table.values()) {
        decl.refs = decl.refs.filter((ref) => ref !== decl.name && table.has(ref)).sort()
    }
}

// ---------------------------------------------------------------------------
// Method signatures: parsed from the emitted resource classes
// ---------------------------------------------------------------------------

interface SpaceRef {
    space: TypeSpace
    name: string
}

interface ParsedMethod {
    /** SDK client id, e.g. 'featureFlags.update'. */
    id: string
    resource: string
    method: string
    /** Rendered `<T = X>` text, '' when the method is not generic. */
    typeParamsText: string
    /** Rendered parameter list, `Schemas.` qualifiers intact. */
    paramsText: string
    /** Return type text, `Schemas.` qualifiers intact. */
    returnTypeText: string
    jsdoc: string
    refs: SpaceRef[]
    /** Bare response type ref when the return type is a single named type. */
    responseRef: SpaceRef | null
    /** First parameter's type ref when it is a single named type. */
    inputRef: SpaceRef | null
}

/** Import-driven resolution of a bare identifier to its type space. */
type ImportSpaces = Map<string, TypeSpace>

function importSpaceForModule(spec: string): TypeSpace | null {
    if (spec.endsWith('/inputs') || spec === '../inputs') {
        return 'inputs'
    }
    if (spec.endsWith('/query-responses') || spec === '../query-responses') {
        return 'queryResponses'
    }
    if (spec.endsWith('core/config') || spec.endsWith('core/query')) {
        return 'core'
    }
    return null
}

function collectImportSpaces(sf: ts.SourceFile): ImportSpaces {
    const spaces: ImportSpaces = new Map()
    for (const stmt of sf.statements) {
        if (!ts.isImportDeclaration(stmt) || !stmt.importClause?.namedBindings) {
            continue
        }
        const space = importSpaceForModule((stmt.moduleSpecifier as ts.StringLiteral).text)
        if (!space || !ts.isNamedImports(stmt.importClause.namedBindings)) {
            continue
        }
        for (const el of stmt.importClause.namedBindings.elements) {
            spaces.set(el.name.text, space)
        }
    }
    return spaces
}

function collectSignatureRefs(
    node: ts.Node,
    imports: ImportSpaces,
    typeParams: Set<string>,
    out: SpaceRef[],
    fileName: string
): void {
    if (ts.isTypeReferenceNode(node)) {
        const name = node.typeName
        if (ts.isQualifiedName(name) && ts.isIdentifier(name.left) && name.left.text === 'Schemas') {
            out.push({ space: 'schemas', name: name.right.text })
        } else if (ts.isIdentifier(name)) {
            const ident = name.text
            if (!BUILTIN_TYPE_NAMES.has(ident) && !typeParams.has(ident)) {
                const space = imports.get(ident)
                if (!space) {
                    throw new Error(`Unresolvable type reference '${ident}' in ${fileName}`)
                }
                out.push({ space, name: ident })
            }
        }
    }
    node.forEachChild((child) => collectSignatureRefs(child, imports, typeParams, out, fileName))
}

function parseMethodDeclaration(
    sf: ts.SourceFile,
    method: ts.MethodDeclaration,
    resource: string,
    imports: ImportSpaces
): ParsedMethod {
    const methodName = method.name.getText(sf)
    const typeParams = new Set((method.typeParameters ?? []).map((p) => p.name.text))
    const refs: SpaceRef[] = []
    for (const typeParam of method.typeParameters ?? []) {
        if (typeParam.constraint) {
            collectSignatureRefs(typeParam.constraint, imports, typeParams, refs, sf.fileName)
        }
        if (typeParam.default) {
            collectSignatureRefs(typeParam.default, imports, typeParams, refs, sf.fileName)
        }
    }
    const paramParts: string[] = []
    for (const param of method.parameters) {
        if (!param.type) {
            throw new Error(`Untyped parameter on ${resource}.${methodName} in ${sf.fileName}`)
        }
        collectSignatureRefs(param.type, imports, typeParams, refs, sf.fileName)
        const optional = param.questionToken || param.initializer ? '?' : ''
        paramParts.push(`${param.name.getText(sf)}${optional}: ${param.type.getText(sf)}`)
    }
    if (!method.type) {
        throw new Error(`Missing return type on ${resource}.${methodName} in ${sf.fileName}`)
    }
    collectSignatureRefs(method.type, imports, typeParams, refs, sf.fileName)

    const returnTypeText = method.type.getText(sf)
    return {
        id: `${resource}.${methodName}`,
        resource,
        method: methodName,
        typeParamsText: method.typeParameters?.length
            ? `<${method.typeParameters.map((p) => p.getText(sf)).join(', ')}>`
            : '',
        paramsText: paramParts.join(', '),
        returnTypeText,
        jsdoc: jsdocDescription(sf, method),
        refs,
        responseRef: singleTypeRef(unwrapPromise(returnTypeText), imports),
        inputRef: method.parameters.length
            ? singleTypeRef(method.parameters[0]!.type!.getText(sf), imports)
            : null,
    }
}

function unwrapPromise(typeText: string): string {
    const match = /^Promise<([\s\S]+)>$/.exec(typeText.trim())
    return match ? match[1]!.trim() : typeText.trim()
}

function singleTypeRef(typeText: string, imports: ImportSpaces): SpaceRef | null {
    const qualified = /^Schemas\.([A-Za-z_$][\w$]*)$/.exec(typeText)
    if (qualified) {
        return { space: 'schemas', name: qualified[1]! }
    }
    if (/^[A-Za-z_$][\w$]*$/.test(typeText)) {
        const space = imports.get(typeText)
        if (space) {
            return { space, name: typeText }
        }
    }
    return null
}

/** Parse every emitted resource class into per-method signature records. */
function parseResourceMethods(): Map<string, ParsedMethod> {
    const methods = new Map<string, ParsedMethod>()
    const resourcesDir = path.join(GEN_DIR, 'resources')
    for (const file of fs.readdirSync(resourcesDir).sort()) {
        if (!file.endsWith('.ts')) {
            continue
        }
        const resource = path.basename(file, '.ts')
        const sf = readSource(path.join(resourcesDir, file))
        const imports = collectImportSpaces(sf)
        for (const stmt of sf.statements) {
            if (!ts.isClassDeclaration(stmt)) {
                continue
            }
            for (const member of stmt.members) {
                if (ts.isMethodDeclaration(member)) {
                    const parsed = parseMethodDeclaration(sf, member, resource, imports)
                    methods.set(parsed.id, parsed)
                }
            }
        }
    }
    // `query.run` lives on the handwritten QueryBase and is inherited by the
    // generated query resource — surface it explicitly.
    const querySf = readSource(path.join(CORE_DIR, 'query.ts'))
    const queryImports: ImportSpaces = new Map([
        ['RequestOptions', 'core'],
        ['QueryNode', 'core'],
        ['QueryResponse', 'core'],
    ])
    for (const stmt of querySf.statements) {
        if (ts.isClassDeclaration(stmt) && stmt.name?.text === 'QueryBase') {
            for (const member of stmt.members) {
                if (ts.isMethodDeclaration(member) && member.name.getText(querySf) === 'run') {
                    const parsed = parseMethodDeclaration(querySf, member, 'query', queryImports)
                    methods.set(parsed.id, parsed)
                }
            }
        }
    }
    if (!methods.has('query.run')) {
        throw new Error('QueryBase.run not found in src/core/query.ts')
    }
    return methods
}

// ---------------------------------------------------------------------------
// Reachability + collision-safe output naming
// ---------------------------------------------------------------------------

interface NamedTypes {
    /** Reachable declarations keyed by `space:name`. */
    reachable: Map<string, TypeDecl>
    /** Output name for a reachable (space, name) node. */
    outputName: (ref: SpaceRef) => string
}

function spaceKey(ref: SpaceRef): string {
    return `${ref.space}:${ref.name}`
}

function resolveReachableTypes(tables: TypeTables, roots: SpaceRef[]): NamedTypes {
    const reachable = new Map<string, TypeDecl>()
    const queue = [...roots]
    while (queue.length > 0) {
        const ref = queue.pop()!
        const key = spaceKey(ref)
        if (reachable.has(key)) {
            continue
        }
        const decl = tables.get(ref.space)?.get(ref.name)
        if (!decl) {
            throw new Error(`Referenced type not found: ${key}`)
        }
        reachable.set(key, decl)
        for (const child of decl.refs) {
            queue.push({ space: ref.space, name: child })
        }
    }

    // Bare names shared across spaces stay unambiguous by keeping the
    // `Schemas.` qualifier on the namespace-side node only (inputs and
    // query-responses never collide with each other in practice — assert it).
    const spacesByName = new Map<string, Set<TypeSpace>>()
    for (const decl of reachable.values()) {
        let spaces = spacesByName.get(decl.name)
        if (!spaces) {
            spaces = new Set()
            spacesByName.set(decl.name, spaces)
        }
        spaces.add(decl.space)
    }
    for (const [name, spaces] of spacesByName) {
        if (spaces.size > 1) {
            const nonSchemas = [...spaces].filter((s) => s !== 'schemas')
            if (nonSchemas.length > 1) {
                throw new Error(`Type name '${name}' collides across non-schemas spaces: ${nonSchemas.join(', ')}`)
            }
        }
    }
    const outputName = (ref: SpaceRef): string => {
        const collides = (spacesByName.get(ref.name)?.size ?? 0) > 1
        return collides && ref.space === 'schemas' ? `Schemas.${ref.name}` : ref.name
    }
    return { reachable, outputName }
}

/** Strip `Schemas.` qualifiers except where the bare name would be ambiguous. */
function rewriteQualifiers(typeText: string, named: NamedTypes): string {
    return typeText.replace(/\bSchemas\.([A-Za-z_$][\w$]*)/g, (_, name: string) =>
        named.outputName({ space: 'schemas', name })
    )
}

// ---------------------------------------------------------------------------
// Classifier helpers
// ---------------------------------------------------------------------------

/** Convert a handler path template literal into an OpenAPI-style template. */
function extractPathTemplate(requestArgText: string, id: string): string {
    const match = /path:\s*`([^`]*)`/.exec(requestArgText)
    if (!match) {
        throw new Error(`No path template literal found for ${id}`)
    }
    const template = match[1]!.replace(/\$\{encodeURIComponent\(String\((.*?)\)\)\}/g, (_, expr: string) => {
        if (expr === 'projectId') {
            return '{project_id}'
        }
        if (expr === 'orgId') {
            return '{organization_id}'
        }
        const paramMatch = /^params\.([A-Za-z_$][\w$]*)$/.exec(expr)
        if (paramMatch) {
            return `{${paramMatch[1]!}}`
        }
        if (/^[A-Za-z_$][\w$]*$/.test(expr)) {
            return `{${expr}}`
        }
        throw new Error(`Unsupported path placeholder expression '${expr}' for ${id}`)
    })
    if (template.includes('${')) {
        throw new Error(`Unconverted path placeholder in '${template}' for ${id}`)
    }
    return template
}

const PROJECTS_PREFIX = '/api/projects/'
const ENVIRONMENTS_PREFIX = '/api/environments/'

function pathAliases(pathTemplate: string): string[] {
    if (pathTemplate.startsWith(PROJECTS_PREFIX)) {
        return [ENVIRONMENTS_PREFIX + pathTemplate.slice(PROJECTS_PREFIX.length)]
    }
    if (pathTemplate.startsWith(ENVIRONMENTS_PREFIX)) {
        return [PROJECTS_PREFIX + pathTemplate.slice(ENVIRONMENTS_PREFIX.length)]
    }
    return []
}

/** 'featureFlags' → 'feature flag' — best-effort human singular for plan lines. */
function humanSingular(resourceProp: string): string {
    const words = resourceProp
        .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
        .toLowerCase()
        .split(' ')
    const last = words[words.length - 1]!
    words[words.length - 1] = singularizeWord(last)
    return words.join(' ')
}

function singularizeWord(word: string): string {
    if (word.endsWith('ies') && word.length > 3) {
        return `${word.slice(0, -3)}y`
    }
    // Uncountables and false plurals: analytics, status, apm span "ss" etc.
    if (/(ss|us|ics)$/.test(word)) {
        return word
    }
    if (word.endsWith('s') && word.length > 1) {
        return word.slice(0, -1)
    }
    return word
}

interface IdField {
    name: string
    type: 'number' | 'string'
}

function idFieldsFromProps(props: Map<string, string> | null): IdField[] {
    const idType = props?.get('id')
    if (idType) {
        return [{ name: 'id', type: idType.includes('string') ? 'string' : 'number' }]
    }
    return [{ name: 'id', type: 'number' }]
}

function displayNameFieldsFromProps(
    responseProps: Map<string, string> | null,
    inputProps: Map<string, string> | null
): string[] {
    for (const props of [responseProps, inputProps]) {
        if (!props) {
            continue
        }
        if (props.has('key') && props.has('name')) {
            return ['key', 'name']
        }
        if (props.has('name')) {
            return ['name']
        }
    }
    return ['id']
}

// ---------------------------------------------------------------------------
// Artifact assembly
// ---------------------------------------------------------------------------

interface DiscoveryMethodEntry {
    id: string
    toolName: string | null
    signature: string
    title: string
    description: string
    category: string
    scopes: string[]
    referencedTypes: string[]
}

interface DiscoveryTypeEntry {
    name: string
    declaration: string
    referencedTypes: string[]
    tokens: number
}

interface ClassifierEntry {
    id: string
    method: string
    pathTemplate: string
    pathAliases: string[]
    readOnly: boolean
    destructive: boolean
    softDelete: boolean
    objectType: string
    displayNameFields: string[]
    scopes: string[]
    idFields: IdField[]
}

// `query.run` has no MCP tool behind it — metadata is authored here, matching
// the query wrappers' category and scope so it groups with them in discovery.
const QUERY_RUN_METADATA = {
    title: 'Run a raw query',
    category: 'Query wrappers',
    scopes: ['query:read'],
}

const QUERY_ENDPOINT_OPERATION: ClassifierEntry = {
    id: 'query.run',
    method: 'POST',
    pathTemplate: '/api/environments/{project_id}/query/',
    pathAliases: ['/api/projects/{project_id}/query/'],
    // The query endpoint is the read path for every query wrapper and the
    // `query.run` escape hatch — without this entry the fail-closed classifier
    // would treat the most important read in the SDK as a phantom mutation.
    readOnly: true,
    destructive: false,
    softDelete: false,
    objectType: 'query',
    displayNameFields: ['id'],
    scopes: QUERY_RUN_METADATA.scopes,
    idFields: [{ name: 'id', type: 'number' }],
}

function buildDiscoveryMethods(
    model: CodeExecMethodModel[],
    parsed: Map<string, ParsedMethod>,
    toolDefs: Record<string, ToolDefinition>,
    named: NamedTypes
): DiscoveryMethodEntry[] {
    const entries: DiscoveryMethodEntry[] = []
    const renderEntry = (pm: ParsedMethod, toolName: string | null): DiscoveryMethodEntry => {
        const def = toolName ? toolDefs[toolName] : undefined
        if (toolName && !def) {
            throw new Error(`Tool definition missing for ${toolName} (${pm.id})`)
        }
        const params = rewriteQualifiers(pm.paramsText, named)
        const returnType = rewriteQualifiers(pm.returnTypeText, named)
        const referencedTypes = [...new Set(pm.refs.map((ref) => named.outputName(ref)))].sort()
        return {
            id: pm.id,
            toolName,
            signature: `${pm.id}${rewriteQualifiers(pm.typeParamsText, named)}(${params}): ${returnType}`,
            title: def ? (def.title ?? def.summary ?? '') : QUERY_RUN_METADATA.title,
            description: def?.description || pm.jsdoc,
            category: def ? (def.category ?? '') : QUERY_RUN_METADATA.category,
            scopes: def ? (def.required_scopes ?? []) : QUERY_RUN_METADATA.scopes,
            referencedTypes,
        }
    }
    for (const m of model) {
        const pm = parsed.get(`${m.resource}.${m.method}`)
        if (!pm) {
            throw new Error(`Emitted SDK method not found for ${m.resource}.${m.method}`)
        }
        entries.push(renderEntry(pm, m.toolName))
    }
    entries.push(renderEntry(parsed.get('query.run')!, null))
    entries.sort((a, b) => compareStrings(a.id, b.id))
    return entries
}

function buildDiscoveryTypes(named: NamedTypes): DiscoveryTypeEntry[] {
    const entries: DiscoveryTypeEntry[] = []
    for (const decl of named.reachable.values()) {
        const declaration = decl.declaration
        entries.push({
            name: named.outputName(decl),
            declaration,
            referencedTypes: decl.refs.map((ref) => named.outputName({ space: decl.space, name: ref })).sort(),
            tokens: Math.ceil(declaration.length / 4),
        })
    }
    entries.sort((a, b) => compareStrings(a.name, b.name))
    return entries
}

function buildClassifierTable(
    model: CodeExecMethodModel[],
    parsed: Map<string, ParsedMethod>,
    tables: TypeTables,
    toolDefs: Record<string, ToolDefinition>
): ClassifierEntry[] {
    const entries: ClassifierEntry[] = [QUERY_ENDPOINT_OPERATION]
    for (const m of model) {
        if (m.isWrapper) {
            continue // all wrappers route through the query endpoint entry
        }
        if (!m.httpMethod || !m.requestArgText) {
            throw new Error(`Handler method ${m.resource}.${m.method} is missing request metadata`)
        }
        const id = `${m.resource}.${m.method}`
        const def = toolDefs[m.toolName]
        if (!def?.annotations) {
            throw new Error(`Tool definition or annotations missing for ${m.toolName} (${id})`)
        }
        const pm = parsed.get(id)
        if (!pm) {
            throw new Error(`Emitted SDK method not found for ${id}`)
        }
        const responseProps = pm.responseRef ? (tables.get(pm.responseRef.space)?.get(pm.responseRef.name)?.props ?? null) : null
        const inputProps = pm.inputRef ? (tables.get(pm.inputRef.space)?.get(pm.inputRef.name)?.props ?? null) : null
        const destructive = def.annotations.destructiveHint === true
        // YAML `soft_delete: true | <field>` compiles to a PATCH whose body is a
        // single `{ <field>: true }` literal (`deleted` or e.g. `archived`) — on
        // the wire it is indistinguishable from an update, so the marker is what
        // lets the plan renderer show it as a delete.
        const softDelete =
            m.httpMethod === 'PATCH' && destructive && /body:\s*\{\s*[A-Za-z_$][\w$]*:\s*true\s*\}/.test(m.requestArgText)
        entries.push({
            id,
            method: m.httpMethod,
            pathTemplate: extractPathTemplate(m.requestArgText, id),
            pathAliases: [],
            readOnly: def.annotations.readOnlyHint === true,
            destructive,
            softDelete,
            objectType: humanSingular(m.resource),
            displayNameFields: displayNameFieldsFromProps(responseProps, inputProps),
            scopes: def.required_scopes ?? [],
            idFields: idFieldsFromProps(responseProps),
        })
    }
    for (const entry of entries) {
        if (entry.pathAliases.length === 0) {
            entry.pathAliases = pathAliases(entry.pathTemplate)
        }
    }
    entries.sort((a, b) => compareStrings(a.id, b.id))

    // The runtime classifier matches on (method, path); entries sharing that
    // key may differ on softDelete/destructive (delete vs update on the same
    // route, disambiguated by body) but must never disagree on readOnly.
    const readOnlyByRoute = new Map<string, boolean>()
    for (const entry of entries) {
        const route = `${entry.method} ${entry.pathTemplate}`
        const seen = readOnlyByRoute.get(route)
        if (seen !== undefined && seen !== entry.readOnly) {
            throw new Error(`Conflicting readOnly classification for route '${route}'`)
        }
        readOnlyByRoute.set(route, entry.readOnly)
    }
    return entries
}

// ---------------------------------------------------------------------------
// Emission
// ---------------------------------------------------------------------------

function buildSdkDts(): string {
    // The dts rollup is built from the sources emitted earlier in this run so
    // the compile-gate bundle can never drift from the discovery surface.
    const tsup = path.join(SDK_ROOT, 'node_modules/.bin/tsup')
    const result = spawnSync(tsup, [], { cwd: SDK_ROOT, stdio: 'pipe' })
    if (result.status !== 0) {
        throw new Error(`tsup build failed (${result.status}): ${result.stderr?.toString().slice(0, 2000)}`)
    }
    return fs.readFileSync(DTS_PATH, 'utf8')
}

function writeJson(filePath: string, value: unknown): void {
    fs.writeFileSync(filePath, `${JSON.stringify(value, null, 4)}\n`)
}

/** Format with the repo oxfmt config so committed bytes survive lint-staged. */
function formatArtifacts(files: string[]): void {
    const oxfmt = path.join(SDK_ROOT, 'node_modules/.bin/oxfmt')
    if (!fs.existsSync(oxfmt)) {
        throw new Error('oxfmt not found — code-exec artifacts would drift from lint-staged formatting')
    }
    const result = spawnSync(oxfmt, files, { cwd: REPO_ROOT, stdio: 'pipe' })
    if (result.status !== 0) {
        throw new Error(`oxfmt failed on code-exec artifacts: ${result.stderr?.toString().slice(0, 500)}`)
    }
}

export function emitCodeExecArtifacts(model: CodeExecMethodModel[]): CodeExecSummary {
    const toolDefs = JSON.parse(fs.readFileSync(TOOL_DEFS_PATH, 'utf8')) as Record<string, ToolDefinition>

    const tables: TypeTables = new Map([
        ['inputs', parseTopLevelTypes(path.join(GEN_DIR, 'inputs.ts'), 'inputs')],
        ['queryResponses', parseTopLevelTypes(path.join(GEN_DIR, 'query-responses.ts'), 'queryResponses')],
        ['schemas', parseSchemasNamespace(path.join(GEN_DIR, 'schemas.ts'))],
        ['core', parseCoreTypes()],
    ])
    const parsed = parseResourceMethods()

    const roots: SpaceRef[] = []
    for (const pm of parsed.values()) {
        roots.push(...pm.refs)
    }
    const named = resolveReachableTypes(tables, roots)

    const methods = buildDiscoveryMethods(model, parsed, toolDefs, named)
    const types = buildDiscoveryTypes(named)
    const operations = buildClassifierTable(model, parsed, tables, toolDefs)
    const dts = buildSdkDts()

    fs.mkdirSync(OUT_DIR, { recursive: true })
    const discoveryPath = path.join(OUT_DIR, 'discovery-index.json')
    const classifierPath = path.join(OUT_DIR, 'classifier-table.json')
    const dtsPath = path.join(OUT_DIR, 'sdk-dts.ts')
    writeJson(discoveryPath, { version: 1, methods, types })
    writeJson(classifierPath, { version: 1, operations })
    fs.writeFileSync(
        dtsPath,
        [
            '// Generated by @posthog/sdk codegen — do not edit.',
            '// Regenerate with: hogli build:openapi  (or: pnpm --filter=@posthog/sdk run generate)',
            '/** Bundled .d.ts of @posthog/sdk, keyed by virtual path under /node_modules/@posthog/sdk/. */',
            `export const SDK_DTS: Record<string, string> = {`,
            `    'index.d.ts': ${JSON.stringify(dts)},`,
            `}`,
            '',
        ].join('\n')
    )
    formatArtifacts([discoveryPath, classifierPath, dtsPath])

    return { methods: methods.length, types: types.length, operations: operations.length, dtsBytes: dts.length }
}
