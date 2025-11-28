#!/usr/bin/env node
/* eslint-disable no-console */
import { execSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const frontendRoot = path.resolve(__dirname, '..')
const repoRoot = path.resolve(frontendRoot, '..')
const productsDir = path.resolve(repoRoot, 'products')

const defaultSchemaPath = path.resolve(frontendRoot, 'src', 'types', 'api', 'openapi.json')

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

function generateTypesForSchema(schemaFile, outputDir, tag, tmpDir) {
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
        generateTypesForSchema(tempFile, outputDir, tags[0], tmpDir)
        console.log(`   → ${path.relative(repoRoot, outputDir)}/index.ts ✓`)
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
