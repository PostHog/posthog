#!/usr/bin/env node
/* eslint-disable no-console */
import { execSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const frontendRoot = path.resolve(__dirname, '..')
const repoRoot = path.resolve(frontendRoot, '..')
const productsDir = path.resolve(repoRoot, 'products')

/**
 * Canonical type sources - these are the authoritative definitions for TS-owned types.
 * Generated types matching these will be replaced with re-exports.
 * Types marked @deprecated are excluded (allows gradual migration to generated types).
 */
const CANONICAL_TYPE_SOURCES = [
    { path: 'frontend/src/types.ts', importPath: '~/types' },
    { path: 'frontend/src/queries/schema/schema-general.ts', importPath: '~/queries/schema' },
    { path: 'frontend/src/queries/schema/schema-surveys.ts', importPath: '~/queries/schema' },
    { path: 'frontend/src/queries/schema/schema-assistant-replay.ts', importPath: '~/queries/schema' },
    { path: 'frontend/src/queries/schema/schema-assistant-queries.ts', importPath: '~/queries/schema' },
    { path: 'frontend/src/queries/schema/schema-assistant-messages.ts', importPath: '~/queries/schema' },
]

/**
 * Extract exported type/interface/enum names from a TypeScript file.
 * Returns Map of typeName → { isDeprecated: boolean }
 */
function getExportedTypeNames(filePath) {
    if (!fs.existsSync(filePath)) {
        return new Map()
    }

    const content = fs.readFileSync(filePath, 'utf8')
    const sourceFile = ts.createSourceFile(filePath, content, ts.ScriptTarget.Latest, true)
    const types = new Map()

    ts.forEachChild(sourceFile, (node) => {
        const isExported = node.modifiers?.some((m) => m.kind === ts.SyntaxKind.ExportKeyword)
        if (!isExported) {
            return
        }

        let name = null
        if (ts.isInterfaceDeclaration(node) || ts.isTypeAliasDeclaration(node) || ts.isEnumDeclaration(node)) {
            name = node.name.text
        }

        if (name) {
            // Check for @deprecated JSDoc tag
            const jsDocTags = ts.getJSDocTags(node)
            const isDeprecated = jsDocTags.some((tag) => tag.tagName.text === 'deprecated')
            types.set(name, { isDeprecated })
        }
    })

    return types
}

/**
 * Build a map of canonical type names → { importPath, isDeprecated }
 * Merges all canonical sources, with earlier sources taking precedence.
 */
function buildCanonicalTypesMap() {
    const canonicalTypes = new Map()

    for (const source of CANONICAL_TYPE_SOURCES) {
        const fullPath = path.resolve(repoRoot, source.path)
        const types = getExportedTypeNames(fullPath)

        for (const [typeName, info] of types) {
            if (!canonicalTypes.has(typeName)) {
                canonicalTypes.set(typeName, {
                    importPath: source.importPath,
                    sourcePath: source.path,
                    isDeprecated: info.isDeprecated,
                })
            }
        }
    }

    return canonicalTypes
}

/**
 * Batch check type equivalence for multiple types at once.
 * Returns a Set of type names that ARE equivalent (passed the check).
 * Uses TypeScript compiler API directly (no subprocess).
 *
 * @param {string} generatedFile - Path to the generated schema file
 * @param {Array<{typeName: string, canonicalFile: string}>} candidates - Types to check
 * @returns {Set<string>} - Type names that are equivalent to their canonical versions
 */
function batchCheckTypeEquivalence(generatedFile, candidates) {
    if (candidates.length === 0) {
        return new Set()
    }

    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-type-check-'))
    const checkFile = path.join(tmpDir, 'check.ts')

    // Calculate relative paths from check file
    const genRelPath = path.relative(tmpDir, generatedFile).replace(/\.ts$/, '').replace(/\\/g, '/')

    // Group candidates by canonical file for import efficiency
    const byCanonicalFile = new Map()
    for (const c of candidates) {
        if (!byCanonicalFile.has(c.canonicalFile)) {
            byCanonicalFile.set(c.canonicalFile, [])
        }
        byCanonicalFile.get(c.canonicalFile).push(c.typeName)
    }

    // Build imports
    const imports = [`import type * as Gen from '${genRelPath}'`]
    let aliasCounter = 0
    const canonicalAliases = new Map() // file → alias
    for (const canonFile of byCanonicalFile.keys()) {
        const alias = `Canon${aliasCounter++}`
        const relPath = path.relative(tmpDir, canonFile).replace(/\.ts$/, '').replace(/\\/g, '/')
        imports.push(`import type * as ${alias} from '${relPath}'`)
        canonicalAliases.set(canonFile, alias)
    }

    // Build individual check types - each one that compiles means equivalence
    const checks = []
    for (const c of candidates) {
        const alias = canonicalAliases.get(c.canonicalFile)
        checks.push(
            `type _Check_${c.typeName}_Forward = Gen.${c.typeName} extends ${alias}.${c.typeName} ? true : never`
        )
        checks.push(
            `type _Check_${c.typeName}_Backward = ${alias}.${c.typeName} extends Gen.${c.typeName} ? true : never`
        )
        checks.push(`const _verify_${c.typeName}: _Check_${c.typeName}_Forward & _Check_${c.typeName}_Backward = true`)
    }

    const checkContent = imports.join('\n') + '\n\n' + checks.join('\n')
    fs.writeFileSync(checkFile, checkContent)

    // Use TS compiler API directly (faster than spawning tsc subprocess)
    const program = ts.createProgram([checkFile], {
        noEmit: true,
        strict: true,
    })
    const diagnostics = ts.getPreEmitDiagnostics(program)

    fs.rmSync(tmpDir, { recursive: true, force: true })

    if (diagnostics.length === 0) {
        // All checks passed!
        return new Set(candidates.map((c) => c.typeName))
    }

    // Parse which types failed from diagnostics
    const failedTypes = new Set()
    for (const diagnostic of diagnostics) {
        const message = ts.flattenDiagnosticMessageText(diagnostic.messageText, '\n')
        for (const c of candidates) {
            if (message.includes(`_Check_${c.typeName}_`) || message.includes(`_verify_${c.typeName}`)) {
                failedTypes.add(c.typeName)
            }
        }
    }

    // Return types that didn't fail
    return new Set(candidates.filter((c) => !failedTypes.has(c.typeName)).map((c) => c.typeName))
}

/**
 * Get exported type declarations from a file using TS AST.
 * Returns array of { typeName, node, start, end } for type aliases and interfaces.
 */
function getExportedTypeDeclarations(filePath) {
    if (!fs.existsSync(filePath)) {
        return []
    }

    const content = fs.readFileSync(filePath, 'utf8')
    const sourceFile = ts.createSourceFile(filePath, content, ts.ScriptTarget.Latest, true)
    const types = []

    ts.forEachChild(sourceFile, (node) => {
        const isExported = node.modifiers?.some((m) => m.kind === ts.SyntaxKind.ExportKeyword)
        if (!isExported) {
            return
        }

        if (ts.isTypeAliasDeclaration(node) || ts.isInterfaceDeclaration(node)) {
            // Get the full range including leading trivia (comments, whitespace)
            const fullStart = node.getFullStart()
            const end = node.getEnd()

            types.push({
                typeName: node.name.text,
                kind: ts.isTypeAliasDeclaration(node) ? 'type' : 'interface',
                fullStart,
                start: node.getStart(),
                end,
            })
        }
    })

    return types
}

/**
 * Deduplicate types in a generated schema file using TS AST.
 * For each type that matches a canonical source (same name, equivalent shape, not deprecated),
 * replace the definition with a re-export from the canonical source.
 */
function deduplicateTypes(schemaFile, canonicalTypes) {
    if (!fs.existsSync(schemaFile)) {
        return { deduplicated: 0, skippedDeprecated: [] }
    }

    const content = fs.readFileSync(schemaFile, 'utf8')
    const generatedTypes = getExportedTypeDeclarations(schemaFile)

    // Build list of candidates (types that exist in both generated and canonical, not deprecated)
    const candidates = []
    const skippedDeprecated = []
    const generatedByName = new Map() // typeName → generated type info

    for (const gen of generatedTypes) {
        const canonical = canonicalTypes.get(gen.typeName)
        if (!canonical) {
            continue
        }

        // Skip deprecated types - these should use the generated version
        if (canonical.isDeprecated) {
            skippedDeprecated.push(gen.typeName)
            continue
        }

        const canonicalFullPath = path.resolve(repoRoot, canonical.sourcePath)
        candidates.push({
            typeName: gen.typeName,
            canonicalFile: canonicalFullPath,
        })
        generatedByName.set(gen.typeName, { ...gen, importPath: canonical.importPath })
    }

    // Batch check all candidates at once (single tsc invocation)
    const equivalentTypes = batchCheckTypeEquivalence(schemaFile, candidates)

    // Build replacements from equivalent types
    const replacements = []
    const reExportsByImportPath = new Map()

    for (const typeName of equivalentTypes) {
        const gen = generatedByName.get(typeName)
        replacements.push({
            typeName,
            fullStart: gen.fullStart,
            end: gen.end,
            importPath: gen.importPath,
        })

        if (!reExportsByImportPath.has(gen.importPath)) {
            reExportsByImportPath.set(gen.importPath, new Set())
        }
        reExportsByImportPath.get(gen.importPath).add(typeName)
    }

    if (replacements.length === 0) {
        return { deduplicated: 0, skippedDeprecated }
    }

    // Sort replacements by position (descending) so we can splice from end to start
    replacements.sort((a, b) => b.fullStart - a.fullStart)

    // Remove the type definitions from the content
    let newContent = content
    for (const r of replacements) {
        newContent = newContent.slice(0, r.fullStart) + newContent.slice(r.end)
    }

    // Build re-export statements
    const reExportStatements = []
    for (const [importPath, typeNames] of reExportsByImportPath) {
        const sortedNames = [...typeNames].sort()
        reExportStatements.push(`export type { ${sortedNames.join(', ')} } from '${importPath}'`)
    }

    // Find insertion point using AST - after last import, or after header comments if no imports
    const sourceFile = ts.createSourceFile(schemaFile, newContent, ts.ScriptTarget.Latest, true)
    let lastImportEnd = 0
    let firstNodeStart = newContent.length

    ts.forEachChild(sourceFile, (node) => {
        // Track first non-import node position (getStart() skips leading trivia like comments)
        if (!ts.isImportDeclaration(node) && node.getStart() < firstNodeStart) {
            firstNodeStart = node.getStart()
        }

        // Track last import position
        if (ts.isImportDeclaration(node)) {
            const end = node.getEnd()
            // Include trailing newline if present
            const afterNode = newContent.slice(end, end + 1)
            lastImportEnd = afterNode === '\n' ? end + 1 : end
        }
    })

    // Insert after last import, or after header comments if no imports
    const insertPosition = lastImportEnd > 0 ? lastImportEnd : firstNodeStart

    // Insert re-export block
    const reExportBlock =
        '\n// Re-exported from canonical sources (TS-owned types)\n' + reExportStatements.join('\n') + '\n'

    newContent = newContent.slice(0, insertPosition) + reExportBlock + newContent.slice(insertPosition)

    // Clean up multiple consecutive blank lines
    newContent = newContent.replace(/\n{3,}/g, '\n\n')

    fs.writeFileSync(schemaFile, newContent)

    return { deduplicated: replacements.length, skippedDeprecated }
}

// Default to temp location (gitignored ephemeral artifact)
const defaultSchemaPath = path.resolve(frontendRoot, 'tmp', 'openapi.json')

const schemaPath = process.env.OPENAPI_SCHEMA_PATH
    ? path.resolve(frontendRoot, process.env.OPENAPI_SCHEMA_PATH)
    : defaultSchemaPath

if (!fs.existsSync(schemaPath)) {
    console.error(`OpenAPI schema not found at ${schemaPath}. Generate it with \`hogli build:openapi-schema\` first.`)
    process.exit(1)
}

// --all flag: generate types for ALL endpoints (ignores tag filtering)
// Useful for finding type overlaps to identify which viewsets need tagging
const generateAll = process.argv.includes('--all')

/**
 * Load products.json and build mappings for tag → product routing.
 *
 * Returns:
 * - knownProducts: Set of all valid product names from products.json (whitelist)
 * - intentToProduct: Map of intent (tag) → product name
 * - productFoldersOnDisk: Set of product folder names that exist in products/
 */
function loadProductMappings() {
    const productsJsonPath = path.resolve(frontendRoot, 'src', 'products.json')
    const productFoldersOnDisk = discoverProductFolders()

    if (!fs.existsSync(productsJsonPath)) {
        console.warn('Warning: products.json not found, falling back to filesystem discovery')
        return {
            knownProducts: productFoldersOnDisk,
            intentToProduct: new Map(),
            productFoldersOnDisk,
        }
    }

    const productsData = JSON.parse(fs.readFileSync(productsJsonPath, 'utf8'))
    const knownProducts = new Set()
    const intentToProduct = new Map()

    // Process all product categories (products, metadata, games)
    for (const category of ['products', 'metadata', 'games']) {
        for (const item of productsData[category] || []) {
            // Convert path to folder name: "Feature flags" → "feature_flags"
            const productName = item.path.toLowerCase().replace(/\s+/g, '_')
            knownProducts.add(productName)

            // Map intents to product name
            for (const intent of item.intents || []) {
                intentToProduct.set(intent, productName)
            }
        }
    }

    return { knownProducts, intentToProduct, productFoldersOnDisk }
}

/**
 * Discover product folders that are ready for TypeScript types.
 * A product is ready if it has a package.json (indicating it's a proper TS package).
 */
function discoverProductFolders() {
    const products = new Set()
    for (const entry of fs.readdirSync(productsDir, { withFileTypes: true })) {
        if (entry.isDirectory() && !entry.name.startsWith('_')) {
            // Only include products that have package.json (ready for TS)
            const packageJsonPath = path.join(productsDir, entry.name, 'package.json')
            if (fs.existsSync(packageJsonPath)) {
                products.add(entry.name)
            }
        }
    }
    return products
}

/**
 * LEVEL 1: Resolve tag → product name
 *
 * Checks both:
 * 1. products.json (products with manifest.tsx)
 * 2. Product folders with package.json (products ready for TS but without manifest)
 *
 * Returns null if tag doesn't map to any known product → goes to "core"
 */
function resolveTagToProduct(tag, mappings) {
    const { knownProducts, intentToProduct, productFoldersOnDisk } = mappings
    const normalizedTag = tag.replace(/-/g, '_')

    // Direct match to known product from products.json
    if (knownProducts.has(normalizedTag)) {
        return normalizedTag
    }

    // Check intent mapping from products.json
    if (intentToProduct.has(tag)) {
        return intentToProduct.get(tag)
    }
    if (intentToProduct.has(normalizedTag)) {
        return intentToProduct.get(normalizedTag)
    }

    // Check if tag matches a product folder on disk (has package.json but no manifest.tsx)
    // This handles products like batch_exports that are TS-ready but not in products.json
    if (productFoldersOnDisk.has(normalizedTag)) {
        return normalizedTag
    }

    // No product match - this goes to "core"
    return null
}

/**
 * LEVEL 2: Resolve product name → output directory
 *
 * If product folder exists on disk → products/{product}/frontend/generated/
 * Otherwise → frontend/src/generated/{product}/
 */
function resolveProductToOutputDir(product, productFoldersOnDisk) {
    if (product === null) {
        // No product - use core
        return path.resolve(frontendRoot, 'src', 'generated', 'core')
    }

    if (productFoldersOnDisk.has(product)) {
        return path.resolve(productsDir, product, 'frontend', 'generated')
    }

    // Product exists in products.json but folder not yet created
    return path.resolve(frontendRoot, 'src', 'generated', product)
}

/**
 * Combined: tag → output directory (for convenience)
 */
function getOutputDirForTag(tag, mappings) {
    const product = resolveTagToProduct(tag, mappings)
    return resolveProductToOutputDir(product, mappings.productFoldersOnDisk)
}

function createTempDir() {
    return fs.mkdtempSync(path.join(os.tmpdir(), 'openapi-split-'))
}

function collectSchemaRefs(obj, refs = new Set()) {
    if (!obj || typeof obj !== 'object') {
        return refs
    }
    if (obj.$ref && typeof obj.$ref === 'string') {
        refs.add(obj.$ref)
    }
    for (const value of Object.values(obj)) {
        collectSchemaRefs(value, refs)
    }
    return refs
}

function resolveNestedRefs(schemas, refs) {
    // Iteratively resolve refs until no new ones are found
    const allRefs = new Set(refs)
    let changed = true
    while (changed) {
        changed = false
        for (const ref of allRefs) {
            const schemaName = ref.replace('#/components/schemas/', '')
            const schema = schemas[schemaName]
            if (schema) {
                const nestedRefs = collectSchemaRefs(schema)
                for (const nestedRef of nestedRefs) {
                    if (!allRefs.has(nestedRef)) {
                        allRefs.add(nestedRef)
                        changed = true
                    }
                }
            }
        }
    }
    return allRefs
}

function buildGroupedSchemasByTag(schema) {
    const grouped = new Map()
    const httpMethods = new Set(['get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace'])
    const allSchemas = schema.components?.schemas ?? {}

    for (const [pathKey, operations] of Object.entries(schema.paths ?? {})) {
        for (const [method, operation] of Object.entries(operations ?? {})) {
            if (!httpMethods.has(method)) {
                continue
            }

            // Use x-explicit-tags (from @extend_schema decorator) instead of auto-derived tags
            const explicitTags = operation['x-explicit-tags']
            const tags = Array.isArray(explicitTags) && explicitTags.length ? explicitTags : []

            for (const tag of tags) {
                if (!grouped.has(tag)) {
                    grouped.set(tag, {
                        openapi: schema.openapi,
                        info: { ...schema.info, title: `${schema.info?.title ?? 'API'} - ${tag}` },
                        paths: {},
                        _refs: new Set(),
                    })
                }

                const entry = grouped.get(tag)
                entry.paths[pathKey] ??= {}
                entry.paths[pathKey][method] = operation

                // Collect schema refs used by this operation
                collectSchemaRefs(operation, entry._refs)
            }
        }
    }

    // Build final schemas with only referenced components
    for (const [tag, entry] of grouped.entries()) {
        const allRefs = resolveNestedRefs(allSchemas, entry._refs)
        const filteredSchemas = {}

        for (const ref of allRefs) {
            const schemaName = ref.replace('#/components/schemas/', '')
            if (allSchemas[schemaName]) {
                filteredSchemas[schemaName] = allSchemas[schemaName]
            }
        }

        // Build final schema object
        grouped.set(tag, {
            openapi: entry.openapi,
            info: entry.info,
            paths: entry.paths,
            components: {
                schemas: filteredSchemas,
            },
        })
    }

    return grouped
}

/**
 * Reorder enums in generated schema file to fix "used before declaration" errors.
 * Orval outputs enums in alphabetical order, not dependency order, causing TS errors.
 * See: https://github.com/orval-labs/orval/issues/1511
 */
function reorderEnumsInSchemaFile(schemaFile) {
    if (!fs.existsSync(schemaFile)) {
        return
    }

    const content = fs.readFileSync(schemaFile, 'utf8')
    const lines = content.split('\n')

    // Find enum declarations (both type and const) and their line ranges
    const enumBlocks = []
    const enumNames = new Set()

    // First pass: identify all enum names (pattern: "export const FooEnum = {" or "export type FooEnum = ")
    for (const line of lines) {
        const constMatch = line.match(/^export const (\w+Enum)\s*=\s*\{/)
        const typeMatch = line.match(/^export type (\w+Enum)\s*=/)
        if (constMatch) {
            enumNames.add(constMatch[1])
        }
        if (typeMatch) {
            enumNames.add(typeMatch[1])
        }
    }

    // Also add BlankEnum and NullEnum which are common DRF patterns
    enumNames.add('BlankEnum')
    enumNames.add('NullEnum')

    // Second pass: extract enum blocks (type + const pairs)
    let i = 0
    while (i < lines.length) {
        const line = lines[i]

        // Check for enum type declaration
        for (const enumName of enumNames) {
            if (line.startsWith(`export type ${enumName} = `)) {
                // Single-line type
                enumBlocks.push({ name: enumName, lines: [line], startIdx: i, endIdx: i, kind: 'type' })
                break
            }
            if (line.startsWith(`export const ${enumName} = `)) {
                // Const declaration - might be single or multi-line
                const blockLines = [line]
                let j = i
                if (!line.includes('as const')) {
                    // Multi-line const
                    while (j < lines.length - 1 && !lines[j].includes('as const')) {
                        j++
                        blockLines.push(lines[j])
                    }
                }
                enumBlocks.push({ name: enumName, lines: blockLines, startIdx: i, endIdx: j, kind: 'const' })
                break
            }
        }
        i++
    }

    if (enumBlocks.length === 0) {
        return // No enums to reorder
    }

    // Sort blocks: put all types first, then consts (each type should precede its const)
    // Group by enum name, type before const
    const blocksByName = new Map()
    for (const block of enumBlocks) {
        if (!blocksByName.has(block.name)) {
            blocksByName.set(block.name, { type: null, const: null })
        }
        blocksByName.get(block.name)[block.kind] = block
    }

    // Build ordered enum section: type then const for each enum
    const orderedEnumLines = []
    for (const [, blocks] of blocksByName) {
        if (blocks.type) {
            orderedEnumLines.push(...blocks.type.lines)
        }
        if (blocks.const) {
            orderedEnumLines.push(...blocks.const.lines)
        }
        orderedEnumLines.push('') // Blank line between enums
    }

    // Remove original enum blocks from content (mark lines for removal)
    const linesToRemove = new Set()
    for (const block of enumBlocks) {
        for (let idx = block.startIdx; idx <= block.endIdx; idx++) {
            linesToRemove.add(idx)
        }
    }

    // Find where to insert enums (after imports/header comments)
    let insertIdx = 0
    for (let idx = 0; idx < lines.length; idx++) {
        const line = lines[idx]
        if (
            line.startsWith('import ') ||
            line.startsWith('export type {') ||
            line.startsWith(' *') ||
            line.startsWith('/*') ||
            line.startsWith('*/') ||
            line.trim() === ''
        ) {
            insertIdx = idx + 1
        } else if (line.startsWith('export ')) {
            break
        }
    }

    // Build new content
    const newLines = []
    for (let idx = 0; idx < lines.length; idx++) {
        if (idx === insertIdx) {
            // Insert all enums here
            newLines.push(...orderedEnumLines)
        }
        if (!linesToRemove.has(idx)) {
            newLines.push(lines[idx])
        }
    }

    // Remove consecutive blank lines
    const cleanedLines = []
    for (let idx = 0; idx < newLines.length; idx++) {
        if (
            newLines[idx].trim() === '' &&
            cleanedLines.length > 0 &&
            cleanedLines[cleanedLines.length - 1].trim() === ''
        ) {
            continue
        }
        cleanedLines.push(newLines[idx])
    }

    fs.writeFileSync(schemaFile, cleanedLines.join('\n'))
}

function generateTypesForSchema(schemaFile, outputDir, tag, tmpDir, canonicalTypes) {
    fs.mkdirSync(outputDir, { recursive: true })

    const outputFile = path.join(outputDir, 'index.ts')

    // Create orval config for this schema - split mode separates schemas from functions
    const configFile = path.join(tmpDir, 'orval.config.mjs')
    const mutatorPath = path.resolve(frontendRoot, 'src', 'lib', 'api-orval-mutator.ts')
    const config = `
import { defineConfig } from 'orval';
export default defineConfig({
  api: {
    input: '${schemaFile}',
    output: {
      target: '${outputFile}',
      mode: 'split',
      client: 'fetch',
      prettier: true,
      override: {
        mutator: {
          path: '${mutatorPath}',
          name: 'apiMutator',
        },
      },
    },
  },
});
`
    fs.writeFileSync(configFile, config)

    execSync(`pnpm exec orval --config "${configFile}"`, {
        stdio: 'inherit',
        cwd: repoRoot,
    })

    // Post-process: reorder enums to fix declaration order issues
    const schemaOutputFile = path.join(outputDir, 'index.schemas.ts')
    reorderEnumsInSchemaFile(schemaOutputFile)

    // Post-process: deduplicate types that exist in canonical sources
    const dedupeResult = deduplicateTypes(schemaOutputFile, canonicalTypes)
    return dedupeResult
}

function mergeSchemas(schemas) {
    // Merge multiple OpenAPI schemas into one
    const merged = {
        openapi: schemas[0].openapi,
        info: { ...schemas[0].info, title: schemas[0].info?.title?.replace(/ - \w+$/, '') || 'API' },
        paths: {},
        components: { schemas: {} },
    }
    for (const schema of schemas) {
        Object.assign(merged.paths, schema.paths)
        Object.assign(merged.components.schemas, schema.components?.schemas || {})
    }
    return merged
}

// Main execution

const schema = JSON.parse(fs.readFileSync(schemaPath, 'utf8'))
const mappings = loadProductMappings()
const tmpDir = createTempDir()
const canonicalTypes = buildCanonicalTypesMap()

console.log(`Loaded ${canonicalTypes.size} canonical types from ${CANONICAL_TYPE_SOURCES.length} source files`)

console.log('')
console.log('┌─────────────────────────────────────────────────────────────────────┐')
if (generateAll) {
    console.log('│  OpenAPI Type Generator (--all mode)                                │')
    console.log('│  Generating types for ALL endpoints to frontend/src/generated/     │')
} else {
    console.log('│  OpenAPI Type Generator                                             │')
    console.log('│  Tags are set via @extend_schema(tags=["product"]) in ViewSets      │')
}
console.log('└─────────────────────────────────────────────────────────────────────┘')
console.log('')

let schemasByOutput

if (generateAll) {
    // --all mode: generate everything to frontend/src/generated/
    const outputDir = path.resolve(frontendRoot, 'src', 'generated')
    const pathCount = Object.keys(schema.paths || {}).length
    const schemaCount = Object.keys(schema.components?.schemas || {}).length
    console.log(`Generating ALL ${pathCount} endpoints, ${schemaCount} schemas`)
    console.log('')
    console.log('─'.repeat(72))
    console.log('')

    schemasByOutput = new Map([[outputDir, { tags: ['all'], schemas: [schema] }]])
} else {
    // Normal mode: filter by tags and route to product folders
    const groupedSchemas = buildGroupedSchemasByTag(schema)

    // Group schemas by output directory
    schemasByOutput = new Map()
    const tagRouting = [] // For logging

    for (const [tag, groupedSchema] of groupedSchemas.entries()) {
        const outputDir = getOutputDirForTag(tag, mappings)

        if (!schemasByOutput.has(outputDir)) {
            schemasByOutput.set(outputDir, { tags: [], schemas: [] })
        }
        schemasByOutput.get(outputDir).tags.push(tag)
        schemasByOutput.get(outputDir).schemas.push(groupedSchema)

        // Track routing for logging
        const relPath = path.relative(repoRoot, outputDir)
        tagRouting.push({ tag, output: relPath })
    }

    // Show tag routing info
    console.log(`Found ${groupedSchemas.size} tags, routing to ${schemasByOutput.size} output directories:`)
    console.log('')

    // Group by output for cleaner display
    const byOutput = new Map()
    for (const { tag, output } of tagRouting) {
        if (!byOutput.has(output)) {
            byOutput.set(output, [])
        }
        byOutput.get(output).push(tag)
    }

    for (const [output, tags] of byOutput) {
        const isProducts = output.startsWith('products/')
        const icon = isProducts ? '📦' : '📁'
        console.log(`  ${icon} ${output}`)
        console.log(`     └─ ${tags.join(', ')}`)
    }

    console.log('')
    console.log('─'.repeat(72))
    console.log('')
}

let generated = 0
let failed = 0
let totalDeduplicated = 0
const allSkippedDeprecated = []
const entries = [...schemasByOutput.entries()]
for (let i = 0; i < entries.length; i++) {
    const [outputDir, { tags, schemas }] = entries[i]
    const mergedSchema = schemas.length > 1 ? mergeSchemas(schemas) : schemas[0]
    const pathCount = Object.keys(mergedSchema.paths).length
    const schemaCount = Object.keys(mergedSchema.components?.schemas || {}).length

    const tagLabel = tags.length > 1 ? `${tags[0]} (+${tags.length - 1} more)` : tags[0]
    const tempFile = path.join(tmpDir, `${tags[0].replace(/[^a-zA-Z0-9_-]/g, '_')}.json`)
    fs.writeFileSync(tempFile, JSON.stringify(mergedSchema, null, 2))

    console.log(`📦 ${tagLabel}`)
    console.log(`   ${pathCount} endpoints, ${schemaCount} schemas`)
    if (tags.length > 1) {
        console.log(`   Merged from: ${tags.join(', ')}`)
    }

    try {
        const dedupeResult = generateTypesForSchema(tempFile, outputDir, tags[0], tmpDir, canonicalTypes)
        console.log(`   → ${path.relative(repoRoot, outputDir)}/index.ts ✓`)
        if (dedupeResult.deduplicated > 0) {
            console.log(`   🔗 Deduplicated ${dedupeResult.deduplicated} types (re-exported from canonical sources)`)
            totalDeduplicated += dedupeResult.deduplicated
        }
        if (dedupeResult.skippedDeprecated.length > 0) {
            allSkippedDeprecated.push(...dedupeResult.skippedDeprecated)
        }
        generated++
    } catch (err) {
        console.error(`   ⚠️  Failed: ${err.message}`)
        failed++
    }

    // Add separator between products (but not after the last one)
    if (i < entries.length - 1) {
        console.log('')
    }
}

// Cleanup temp dir
fs.rmSync(tmpDir, { recursive: true, force: true })

// Check for potential duplicate types in frontend/src
function findPotentialDuplicates(generatedFiles) {
    const duplicates = []
    const frontendSrc = path.resolve(frontendRoot, 'src')

    for (const file of generatedFiles) {
        const content = fs.readFileSync(file, 'utf8')
        // Extract interface/type names from generated file
        const typeNames = [...content.matchAll(/^export (?:interface|type) (\w+)/gm)].map((m) => m[1])

        for (const typeName of typeNames) {
            // Skip response/request types and params - these are generated-specific
            if (
                typeName.endsWith('Response') ||
                typeName.endsWith('Request') ||
                typeName.endsWith('Params') ||
                typeName.startsWith('get') ||
                typeName.includes('Response200') ||
                typeName.includes('Response201')
            ) {
                continue
            }

            // Skip query-related types - these come from JSON schema, not OpenAPI
            if (
                typeName.endsWith('Query') ||
                typeName.endsWith('Filter') ||
                typeName.endsWith('Node') ||
                typeName.endsWith('Result') ||
                typeName.endsWith('Toggle') ||
                typeName.includes('HogQL') ||
                typeName.includes('Breakdown') ||
                typeName.includes('Funnel') ||
                typeName.includes('Retention') ||
                typeName.includes('Trends') ||
                typeName.includes('Paths') ||
                typeName.includes('Lifecycle') ||
                typeName.includes('Stickiness')
            ) {
                continue
            }

            // Search for same name in frontend/src (excluding the generated files)
            try {
                const result = execSync(
                    `rg -l "^export (interface|type) ${typeName}\\b" "${frontendSrc}" --glob "*.ts" --glob "*.tsx" 2>/dev/null || true`,
                    { encoding: 'utf8' }
                ).trim()

                if (result) {
                    const locations = result.split('\n').filter((l) => !l.includes('/api/index.ts'))
                    if (locations.length > 0) {
                        duplicates.push({ typeName, generatedIn: file, manualIn: locations })
                    }
                }
            } catch {
                // rg not found or other error, skip
            }
        }
    }

    return duplicates
}

// Summary
console.log('')
console.log('─'.repeat(72))
console.log('')
console.log(`✅ Generated ${generated} API client(s)${failed > 0 ? `, ${failed} failed` : ''}`)

if (totalDeduplicated > 0) {
    console.log(`🔗 Deduplicated ${totalDeduplicated} types total (replaced with re-exports from canonical sources)`)
}

if (allSkippedDeprecated.length > 0) {
    console.log('')
    console.log(`⏭️  Skipped ${allSkippedDeprecated.length} @deprecated types (kept generated versions):`)
    console.log(
        `   ${allSkippedDeprecated.slice(0, 10).join(', ')}${allSkippedDeprecated.length > 10 ? ` and ${allSkippedDeprecated.length - 10} more...` : ''}`
    )
}

// Check for duplicates - use unique output dirs
const generatedFiles = [...schemasByOutput.keys()]
    .map((dir) => path.join(dir, 'index.ts'))
    .filter((f) => fs.existsSync(f))

const duplicates = findPotentialDuplicates(generatedFiles)
if (duplicates.length > 0) {
    console.log('')
    console.log('⚠️  Potential duplicate types found (manual types that may match generated ones):')
    for (const { typeName, manualIn } of duplicates) {
        console.log(`   ${typeName}`)
        for (const loc of manualIn) {
            console.log(`      └─ ${path.relative(repoRoot, loc)}`)
        }
    }
    console.log('')
    console.log('   Consider removing manual types and importing from generated API client instead.')
}

if (!generateAll && generated === 0) {
    console.log('')
    console.log('💡 To generate types for your product:')
    console.log('   1. Add @extend_schema(tags=["your_product"]) to your ViewSet methods')
    console.log('   2. Ensure products/your_product/frontend/ folder exists')
    console.log('   3. Re-run: ./bin/build-openapi-schema.sh && node frontend/bin/generate-openapi-types.mjs')
}

if (generateAll) {
    console.log('')
    console.log('💡 Now run: node frontend/bin/find-type-overlaps.mjs')
    console.log('   to see which manual types overlap with generated types.')
}
