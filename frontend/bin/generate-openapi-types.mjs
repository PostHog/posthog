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

function discoverProductFolders() {
    const products = new Set()
    for (const entry of fs.readdirSync(productsDir, { withFileTypes: true })) {
        if (entry.isDirectory() && !entry.name.startsWith('_')) {
            products.add(entry.name)
        }
    }
    return products
}

// Tags that should be routed to core (no separate product folder)
const CORE_TAGS = new Set([
    'core',
    'session_recordings', // No separate product folder yet
    'hog_functions', // No separate product folder yet
    'billing', // EE-specific, no product folder
    'max', // Max AI assistant, ee/hogai
])

function getOutputDirForTag(tag, productFolders) {
    if (CORE_TAGS.has(tag)) {
        return path.resolve(frontendRoot, 'src', 'generated')
    }
    // Normalize tag: convert hyphens to underscores to match folder names
    const normalizedTag = tag.replace(/-/g, '_')
    if (productFolders.has(normalizedTag)) {
        return path.resolve(productsDir, normalizedTag, 'frontend', 'generated')
    }
    return null // Tag doesn't match any product or core
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
const productFolders = discoverProductFolders()
const groupedSchemas = buildGroupedSchemasByTag(schema)
const tmpDir = createTempDir()

console.log('')
console.log('┌─────────────────────────────────────────────────────────────────────┐')
console.log('│  OpenAPI Type Generator                                             │')
console.log('│  Tags are set via @extend_schema(tags=["product"]) in ViewSets      │')
console.log('└─────────────────────────────────────────────────────────────────────┘')
console.log('')

// Show tag matching info
const allTags = [...groupedSchemas.keys()].sort()
const matchedTags = allTags.filter((tag) => getOutputDirForTag(tag, productFolders))
const unmatchedTags = allTags.filter((tag) => !getOutputDirForTag(tag, productFolders))
const coreTags = matchedTags.filter((tag) => CORE_TAGS.has(tag))
const productTags = matchedTags.filter((tag) => !CORE_TAGS.has(tag))

console.log(`Found ${allTags.length} tags in schema:`)
console.log(`  Core tags:    ${coreTags.join(', ') || '(none)'}`)
console.log(`  Product tags: ${productTags.join(', ') || '(none)'}`)
if (unmatchedTags.length > 0) {
    console.log(`  Skipped:      ${unmatchedTags.join(', ')}`)
}
console.log('')
console.log('─'.repeat(72))
console.log('')

// Group schemas by output directory to merge CORE_TAGS
const schemasByOutput = new Map()
for (const [tag, groupedSchema] of groupedSchemas.entries()) {
    const outputDir = getOutputDirForTag(tag, productFolders)
    if (!outputDir) {
        continue
    }
    if (!schemasByOutput.has(outputDir)) {
        schemasByOutput.set(outputDir, { tags: [], schemas: [] })
    }
    schemasByOutput.get(outputDir).tags.push(tag)
    schemasByOutput.get(outputDir).schemas.push(groupedSchema)
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

if (unmatchedTags.length > 0 || generated === 0) {
    console.log('')
    console.log('💡 To generate types for your product:')
    console.log('   1. Add @extend_schema(tags=["your_product"]) to your ViewSet methods')
    console.log('   2. Ensure products/your_product/frontend/ folder exists')
    console.log('   3. Re-run: ./bin/build-openapi-schema.sh && node frontend/bin/generate-openapi-types.mjs')
}
