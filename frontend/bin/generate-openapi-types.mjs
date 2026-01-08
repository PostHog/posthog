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
    const productFoldersOnDisk = discoverProductFolders()

    // Tags should match folder names directly (e.g., @extend_schema(tags=["replay"]))
    // No need for complex intent mapping - just use folder names as the source of truth
    return { productFoldersOnDisk }
}

/**
 * Discover product folders that are ready for TypeScript types.
 * A product is ready if it has a package.json (indicating it's a proper TS package).
 */
function discoverProductFolders() {
    const products = new Set()
    for (const entry of fs.readdirSync(productsDir, { withFileTypes: true })) {
        if (entry.isDirectory() && !entry.name.startsWith('_')) {
            products.add(entry.name)
        }
    }
    return products
}

/**
 * Resolve tag → product folder name
 *
 * Tags should match folder names directly (e.g., "replay", "feature_flags").
 * Returns null if tag doesn't match any product folder → goes to "core"
 */
function resolveTagToProduct(tag, mappings) {
    const { productFoldersOnDisk } = mappings
    const normalizedTag = tag.replace(/-/g, '_')

    // Tag must match a product folder on disk
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

/**
 * Group endpoints by output directory.
 * Simple logic:
 * - tag matches product folder → goes there
 * - tag is explicitly "core" → goes to core
 * - no tag or unrecognized tag → skipped (tracked for reporting)
 */
function buildGroupedSchemasByOutput(schema, mappings) {
    const grouped = new Map() // outputDir → { paths, _refs }
    const httpMethods = new Set(['get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace'])
    const allSchemas = schema.components?.schemas ?? {}
    const skippedTags = new Map() // tag → count (for unrecognized tags)
    let skippedNoTags = 0

    for (const [pathKey, operations] of Object.entries(schema.paths ?? {})) {
        for (const [method, operation] of Object.entries(operations ?? {})) {
            if (!httpMethods.has(method)) {
                continue
            }

            // Use x-explicit-tags (from @extend_schema decorator)
            const explicitTags = operation['x-explicit-tags']
            const tags = Array.isArray(explicitTags) && explicitTags.length ? explicitTags : []

            // Find first tag that matches a product folder
            const productTag = tags.find((t) => resolveTagToProduct(t, mappings) !== null)

            let outputDir
            if (productTag) {
                outputDir = resolveProductToOutputDir(productTag, mappings.productFoldersOnDisk)
            } else if (tags.includes('core')) {
                outputDir = resolveProductToOutputDir('core', mappings.productFoldersOnDisk)
            } else {
                // Track skipped endpoints
                if (tags.length === 0) {
                    skippedNoTags++
                } else {
                    for (const tag of tags) {
                        skippedTags.set(tag, (skippedTags.get(tag) || 0) + 1)
                    }
                }
                continue
            }

            if (!grouped.has(outputDir)) {
                grouped.set(outputDir, {
                    openapi: schema.openapi,
                    info: schema.info,
                    paths: {},
                    _refs: new Set(),
                })
            }

            const entry = grouped.get(outputDir)
            entry.paths[pathKey] ??= {}
            entry.paths[pathKey][method] = operation
            collectSchemaRefs(operation, entry._refs)
        }
    }

    // Report skipped endpoints
    if (skippedNoTags > 0 || skippedTags.size > 0) {
        console.log('⚠️  Skipped endpoints (no matching product folder):')
        if (skippedNoTags > 0) {
            console.log(`   ${skippedNoTags} endpoints with no @extend_schema tags`)
        }
        for (const [tag, count] of [...skippedTags.entries()].sort((a, b) => b[1] - a[1])) {
            console.log(`   ${count} endpoints tagged "${tag}"`)
        }
        console.log('')
    }

    // Build final schemas with only referenced components
    for (const [outputDir, entry] of grouped.entries()) {
        const allRefs = resolveNestedRefs(allSchemas, entry._refs)
        const filteredSchemas = {}

        for (const ref of allRefs) {
            const schemaName = ref.replace('#/components/schemas/', '')
            if (allSchemas[schemaName]) {
                filteredSchemas[schemaName] = allSchemas[schemaName]
            }
        }

        grouped.set(outputDir, {
            openapi: entry.openapi,
            info: { ...entry.info, title: `${entry.info?.title ?? 'API'} - ${path.basename(outputDir)}` },
            paths: entry.paths,
            components: { schemas: filteredSchemas },
        })
    }

    return grouped
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

    schemasByOutput = new Map([[outputDir, schema]])
} else {
    // Normal mode: route to product folders or core
    schemasByOutput = buildGroupedSchemasByOutput(schema, mappings)

    // Show routing info
    console.log(`Routing to ${schemasByOutput.size} output directories:`)
    console.log('')

    for (const outputDir of schemasByOutput.keys()) {
        const relPath = path.relative(repoRoot, outputDir)
        const isProducts = relPath.startsWith('products/')
        const icon = isProducts ? '📦' : '📁'
        console.log(`  ${icon} ${relPath}`)
    }

    console.log('')
    console.log('─'.repeat(72))
    console.log('')
}

let generated = 0
let failed = 0
const entries = [...schemasByOutput.entries()]

// Prepare all jobs first (write temp files, log info)
const jobs = entries.map(([outputDir, groupedSchema]) => {
    const pathCount = Object.keys(groupedSchema.paths).length
    const schemaCount = Object.keys(groupedSchema.components?.schemas || {}).length
    // Use product folder name as label (e.g., "batch_exports" from "products/batch_exports/frontend/generated")
    const relPath = path.relative(repoRoot, outputDir)
    const label = relPath.startsWith('products/') ? relPath.split('/')[1] : 'core'
    const tempFile = path.join(tmpDir, `${label}.json`)
    fs.writeFileSync(tempFile, JSON.stringify(groupedSchema, null, 2))

    console.log(`📦 ${label}: ${pathCount} endpoints, ${schemaCount} schemas`)

    return { tempFile, outputDir, label }
})

console.log('')
console.log(`Running ${jobs.length} orval generations in parallel...`)
console.log('')

// Run all orval generations in parallel
const results = await Promise.allSettled(
    jobs.map(async ({ tempFile, outputDir, label }) => {
        const { execSync } = await import('node:child_process')
        const configFile = path.join(tmpDir, `orval-${label}.config.mjs`)
        const outputFile = path.join(outputDir, 'api.ts')
        const mutatorPath = path.resolve(frontendRoot, 'src', 'lib', 'api-orval-mutator.ts')
        // Stub for orval's esbuild bundling - avoids scss import chain
        const apiStubPath = path.resolve(frontendRoot, 'src', 'lib', 'api-stub-for-orval.ts')

        fs.mkdirSync(outputDir, { recursive: true })

        const config = `
import { defineConfig } from 'orval';
export default defineConfig({
  api: {
    input: '${tempFile}',
    output: {
      target: '${outputFile}',
      mode: 'split',
      client: 'fetch',
      prettier: false,
      override: {
        header: (info) => [
          'Auto-generated from the Django backend OpenAPI schema.',
          'To modify these types, update the Django serializers or views, then run:',
          '  hogli build:openapi',
          'Questions or issues? #team-devex on Slack',
          '',
          ...(info?.title ? [info.title] : []),
          ...(info?.version ? ['OpenAPI spec version: ' + info.version] : []),
        ],
        mutator: {
          path: '${mutatorPath}',
          name: 'apiMutator',
          alias: {
            'lib/api': '${apiStubPath}',
          },
        },
        components: {
          schemas: { suffix: 'Api' },
        },
      },
    },
  },
});
`
        fs.writeFileSync(configFile, config)
        execSync(`pnpm exec orval --config "${configFile}"`, { stdio: 'pipe', cwd: repoRoot })

        return { label, outputDir }
    })
)

// Report results and collect output dirs for formatting
const outputDirs = []
for (const result of results) {
    if (result.status === 'fulfilled') {
        console.log(`   ✓ ${result.value.label} → ${path.relative(repoRoot, result.value.outputDir)}`)
        outputDirs.push(result.value.outputDir)
        generated++
    } else {
        console.error(`   ✗ Failed: ${result.reason?.message || result.reason}`)
        failed++
    }
}

// Run prettier once on all generated files
if (outputDirs.length > 0) {
    console.log('')
    console.log('Formatting generated files...')
    const globs = outputDirs.map((d) => `"${d}/**/*.ts"`).join(' ')
    try {
        execSync(`pnpm exec prettier --write ${globs}`, { stdio: 'pipe', cwd: repoRoot })
        console.log('   ✓ Formatted')
    } catch {
        console.log('   ⚠️  Prettier formatting skipped (not critical)')
    }
}

// Cleanup temp dir
fs.rmSync(tmpDir, { recursive: true, force: true })

// Summary
console.log('')
console.log('─'.repeat(72))
console.log('')
console.log(`✅ Generated ${generated} API client(s)${failed > 0 ? `, ${failed} failed` : ''}`)

// Note: Duplicate type detection skipped - with 'Api' suffix on generated types,
// there are no collisions with manual types (e.g., TaskApi vs Task)

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
