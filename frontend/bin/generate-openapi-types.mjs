#!/usr/bin/env node
/* eslint-disable no-console */
import { execSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { collectSchemaRefs, preprocessSchema, resolveNestedRefs, runOrvalParallel } from '@posthog/openapi-codegen'

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

// --no-zod flag: skip Zod schema generation
const skipZod = process.argv.includes('--no-zod')

/**
 * Load product mappings for routing endpoints to output directories.
 *
 * Returns:
 * - productFoldersOnDisk: Set of product folder names that exist in products/
 * - validatedRequestViewSets: Set of ViewSet snake_case names that use @validated_request
 */
function loadProductMappings() {
    const productFoldersOnDisk = discoverProductFolders()
    const validatedRequestViewSets = buildValidatedRequestViewSets()

    return { productFoldersOnDisk, validatedRequestViewSets }
}

/**
 * Discover product folders that are ready for TypeScript types.
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
 * Scan posthog/api/ and ee/ for ViewSets that use @validated_request decorator.
 * These endpoints should be included in core even without explicit tags.
 * Returns: Set of ViewSet snake_case names
 */
function buildValidatedRequestViewSets() {
    const viewSets = new Set()
    const dirsToScan = [path.join(repoRoot, 'posthog', 'api'), path.join(repoRoot, 'ee')]

    for (const dir of dirsToScan) {
        if (!fs.existsSync(dir)) {
            continue
        }

        const pyFiles = findPythonFiles(dir)

        for (const pyFile of pyFiles) {
            try {
                const content = fs.readFileSync(pyFile, 'utf-8')

                // Check if file uses @validated_request
                if (!content.includes('@validated_request')) {
                    continue
                }

                // Find all ViewSet classes in this file (case insensitive)
                const viewSetRegex = /class\s+(\w+ViewSet)[\s(]/gi
                let match
                while ((match = viewSetRegex.exec(content)) !== null) {
                    const viewSetName = match[1]
                    const snakeCase = viewSetName
                        .replace(/ViewSet$/i, '')
                        .replace(/([A-Z])([A-Z][a-z])/g, '$1_$2')
                        .replace(/([a-z])([A-Z])/g, '$1_$2')
                        .toLowerCase()
                    viewSets.add(snakeCase)
                }
            } catch (err) {
                if (err.code !== 'ENOENT' && err.code !== 'EACCES') {
                    console.warn(`Warning: scanning ${pyFile}:`, err.message)
                }
            }
        }
    }

    return viewSets
}

/**
 * Recursively find all .py files in a directory
 */
function findPythonFiles(dir) {
    const files = []
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const fullPath = path.join(dir, entry.name)
        if (entry.isDirectory() && !entry.name.startsWith('__')) {
            files.push(...findPythonFiles(fullPath))
        } else if (entry.isFile() && entry.name.endsWith('.py')) {
            files.push(fullPath)
        }
    }
    return files
}

/**
 * Match URL path to a product folder name.
 * Fallback for endpoints that might not be tagged.
 */
function matchUrlToProduct(urlPath, productFolders) {
    const urlLower = urlPath.toLowerCase().replace(/-/g, '_')
    for (const product of productFolders) {
        if (urlLower.includes(`/${product}/`)) {
            return product
        }
    }
    return null
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

/**
 * Group endpoints by output directory.
 *
 * Routing priority:
 * 1. Tag matches product folder (includes auto-tags from backend) -> product
 * 2. URL path contains product folder name (fallback) -> product
 * 3. @validated_request decorator in posthog/api/ or ee/ -> core
 * 4. Explicit "core" tag -> core
 * 5. Otherwise -> skipped
 */
function buildGroupedSchemasByOutput(schema, mappings) {
    const grouped = new Map()
    const httpMethods = new Set(['get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace'])
    const allSchemas = schema.components?.schemas ?? {}
    const skippedTags = new Map()
    let skippedNoTags = 0
    let routedByTag = 0
    let routedByUrl = 0
    let routedByValidatedRequest = 0

    for (const [pathKey, operations] of Object.entries(schema.paths ?? {})) {
        for (const [method, operation] of Object.entries(operations ?? {})) {
            if (!httpMethods.has(method)) {
                continue
            }

            if (operation.deprecated) {
                continue
            }

            const operationId = operation.operationId || ''
            const explicitTags = operation['x-explicit-tags']
            const tags = Array.isArray(explicitTags) && explicitTags.length ? explicitTags : []

            let outputDir = null
            let routingMethod = null

            // Priority 1: Tag matches product folder (includes auto-tags from backend)
            const productTag = tags.find((t) => resolveTagToProduct(t, mappings) !== null)
            if (productTag) {
                outputDir = resolveProductToOutputDir(productTag, mappings.productFoldersOnDisk)
                routingMethod = 'tag'
            }

            // Priority 2: URL path contains product folder name (fallback)
            if (!outputDir) {
                const urlProduct = matchUrlToProduct(pathKey, mappings.productFoldersOnDisk)
                if (urlProduct) {
                    outputDir = resolveProductToOutputDir(urlProduct, mappings.productFoldersOnDisk)
                    routingMethod = 'url'
                }
            }

            // Priority 3: @validated_request decorator in core -> core
            if (!outputDir) {
                for (const snakeCase of mappings.validatedRequestViewSets) {
                    if (operationId === snakeCase || operationId.startsWith(snakeCase + '_')) {
                        outputDir = resolveProductToOutputDir(null, mappings.productFoldersOnDisk)
                        routingMethod = 'validated_request'
                        break
                    }
                }
            }

            // Priority 4: Explicit "core" tag
            if (!outputDir && tags.includes('core')) {
                outputDir = resolveProductToOutputDir(null, mappings.productFoldersOnDisk)
                routingMethod = 'tag'
            }

            // No match - skip
            if (!outputDir) {
                if (tags.length === 0) {
                    skippedNoTags++
                } else {
                    for (const tag of tags) {
                        skippedTags.set(tag, (skippedTags.get(tag) || 0) + 1)
                    }
                }
                continue
            }

            if (routingMethod === 'tag') {
                routedByTag++
            } else if (routingMethod === 'url') {
                routedByUrl++
            } else if (routingMethod === 'validated_request') {
                routedByValidatedRequest++
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

    // Report routing stats
    console.log(`📊 Routing stats:`)
    console.log(`   ${routedByTag} endpoints routed by tags (includes auto-tags from backend)`)
    console.log(`   ${routedByUrl} endpoints routed by URL path`)
    console.log(`   ${routedByValidatedRequest} endpoints routed by @validated_request decorator`)
    console.log('')

    // Report skipped endpoints
    if (skippedNoTags > 0 || skippedTags.size > 0) {
        console.log('⚠️  Skipped endpoints (no product match or core tag):')
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

        // Inline the full `components.parameters` (and any other top-level
        // component buckets we don't slice) verbatim. The per-product paths
        // reference shared parameter objects like `#/components/parameters/
        // ProjectIdPath` — without these, orval validation fails with
        // INVALID_REFERENCE and silently writes nothing. The parameter set
        // is small and reused across products, so the duplication is fine.
        const sharedComponents = { ...schema.components }
        delete sharedComponents.schemas
        grouped.set(outputDir, {
            openapi: entry.openapi,
            info: { ...entry.info, title: `${entry.info?.title ?? 'API'} - ${path.basename(outputDir)}` },
            paths: entry.paths,
            components: { ...sharedComponents, schemas: filteredSchemas },
        })
    }

    return grouped
}

// Main execution

const schema = preprocessSchema(JSON.parse(fs.readFileSync(schemaPath, 'utf8')))
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

/**
 * Orval emits `export const fooDefault = null` + `.default(fooDefault)` for
 * serializer fields with `default=None`. Zod rejects `.default(null)` on typed
 * schemas (number, string, etc.). Replace with `.nullish().default(null)` to
 * preserve Django's default=None semantics (missing key → null, not undefined).
 */
function fixNullDefaults(filePath) {
    let content = fs.readFileSync(filePath, 'utf-8')

    const nullConsts = new Set()
    for (const m of content.matchAll(/export const (\w+Default)\s*=\s*null\s*;/g)) {
        nullConsts.add(m[1])
    }
    if (nullConsts.size === 0) {
        return
    }

    const namesPattern = [...nullConsts].map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')
    const defaultRe = new RegExp('\\.default\\(\\s*(?:' + namesPattern + ')\\s*[,)]', 'g')
    const constRe = new RegExp('export const (?:' + namesPattern + ')\\s*=\\s*null\\s*;', 'g')
    content = content.replace(defaultRe, '.nullish().default(null)')
    content = content.replace(constRe, '')

    fs.writeFileSync(filePath, content)
}

/**
 * Annotate top-level Zod exports with @__PURE__ so bundlers can tree-shake
 * unused schemas out of the bundle.
 */
function annotatePureZodExports(filePath) {
    const content = fs.readFileSync(filePath, 'utf-8')
    const annotated = content.replace(/^(export const \w+ =) (zod\.)/gm, '$1 /* @__PURE__ */ $2')
    fs.writeFileSync(filePath, annotated)
}

// Prepare all jobs first (write temp files, log info)
const fetchJobs = entries.map(([outputDir, groupedSchema]) => {
    const pathCount = Object.keys(groupedSchema.paths).length
    const schemaCount = Object.keys(groupedSchema.components?.schemas || {}).length
    // Use product folder name as label (e.g., "batch_exports" from "products/batch_exports/frontend/generated")
    const relPath = path.relative(repoRoot, outputDir)
    const label = relPath.startsWith('products/') ? relPath.split('/')[1] : 'core'
    const tempFile = path.join(tmpDir, `${label}.json`)
    fs.writeFileSync(tempFile, JSON.stringify(groupedSchema, null, 2))

    console.log(`📦 ${label}: ${pathCount} endpoints, ${schemaCount} schemas`)

    const outputFile = path.join(outputDir, 'api.ts')
    const mutatorPath = path.resolve(frontendRoot, 'src', 'lib', 'api-orval-mutator.ts')

    fs.mkdirSync(outputDir, { recursive: true })

    const config = {
        input: tempFile,
        output: {
            target: outputFile,
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
                namingConvention: {
                    enum: 'PascalCase',
                },
                fetch: {
                    includeHttpResponseReturnType: false,
                },
                mutator: {
                    path: mutatorPath,
                    name: 'apiMutator',
                    external: ['lib/api'],
                },
                components: {
                    schemas: { suffix: 'Api' },
                },
            },
        },
    }

    return { tempFile, outputDir, label, config, kind: 'fetch' }
})

/**
 * Detect schemas that would cause Orval's Zod output to blow up and replace
 * them with opaque { type: 'object' }.
 *
 * Orval's Zod client fully inlines every $ref instead of using z.lazy(),
 * so recursive types and deeply nested unions (like HogQL query schemas)
 * expand exponentially. TypeScript interfaces handle this fine via forward
 * references, so this transform only runs for the Zod pass.
 *
 * We estimate each schema's "expanded node count" — how many AST nodes
 * would result if all $refs were recursively inlined. Anything above the
 * threshold gets replaced with an opaque object.
 *
 * Mutates the schema in place. Returns the set of opaqued schema names.
 */
const ZOD_EXPANDED_NODE_LIMIT = 1000

function opaqueDeepSchemas(schema) {
    const allSchemas = schema.components?.schemas ?? {}
    const cache = new Map()

    function expandedSize(name, seen) {
        if (cache.has(name)) {
            return cache.get(name)
        }
        if (seen.has(name)) {
            return Infinity
        } // true cycle — will exceed any limit
        const defn = allSchemas[name]
        if (!defn) {
            return 1
        }

        const nextSeen = new Set(seen)
        nextSeen.add(name)

        function countNodes(obj) {
            if (!obj || typeof obj !== 'object') {
                return 1
            }
            if (Array.isArray(obj)) {
                return obj.reduce((sum, item) => sum + countNodes(item), 0)
            }
            if (obj.$ref) {
                const refName = obj.$ref.replace('#/components/schemas/', '')
                return expandedSize(refName, nextSeen)
            }
            let total = 0
            for (const v of Object.values(obj)) {
                total += countNodes(v)
            }
            return Math.max(total, 1)
        }

        const size = countNodes(defn)
        cache.set(name, size)
        return size
    }

    // Compute expanded sizes and collect schemas that exceed the limit
    const opaqued = new Set()
    for (const name of Object.keys(allSchemas)) {
        if (expandedSize(name, new Set()) > ZOD_EXPANDED_NODE_LIMIT) {
            opaqued.add(name)
        }
    }

    // Replace with opaque object type
    for (const name of opaqued) {
        allSchemas[name] = {
            type: 'object',
            description: `Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)`,
            additionalProperties: true,
        }
    }

    return opaqued
}

// Prepare Zod schema jobs — use a separate schema copy with cyclic refs opaqued
const zodJobs = skipZod
    ? []
    : fetchJobs.map((fetchJob) => {
          // Deep-copy the schema and opaque deeply nested schemas for Zod
          const zodSchema = JSON.parse(fs.readFileSync(fetchJob.tempFile, 'utf-8'))
          const opaqued = opaqueDeepSchemas(zodSchema)
          const zodTempFile = path.join(tmpDir, `${fetchJob.label}.zod.json`)
          fs.writeFileSync(zodTempFile, JSON.stringify(zodSchema, null, 2))
          if (opaqued.size > 0) {
              console.log(
                  `   🔄 ${fetchJob.label}: opaqued ${opaqued.size} recursive schema(s): ${[...opaqued].join(', ')}`
              )
          }

          const zodOutputFile = path.join(fetchJob.outputDir, 'api.zod.ts')
          const config = {
              input: zodTempFile,
              output: {
                  target: zodOutputFile,
                  mode: 'split',
                  client: 'zod',
                  prettier: false,
                  override: {
                      header: (info) => [
                          'Auto-generated Zod validation schemas from the Django backend OpenAPI schema.',
                          'To modify these schemas, update the Django serializers or views, then run:',
                          '  hogli build:openapi',
                          'Questions or issues? #team-devex on Slack',
                          '',
                          ...(info?.title ? [info.title] : []),
                          ...(info?.version ? ['OpenAPI spec version: ' + info.version] : []),
                      ],
                      zod: {
                          generate: {
                              param: false,
                              query: false,
                              header: false,
                              body: true,
                              response: false,
                          },
                      },
                      components: {
                          schemas: { suffix: 'Api' },
                      },
                  },
              },
          }
          return {
              tempFile: zodTempFile,
              outputDir: fetchJob.outputDir,
              label: fetchJob.label,
              config,
              kind: 'zod',
          }
      })

const allJobs = [...fetchJobs, ...zodJobs]

console.log('')
if (zodJobs.length > 0) {
    console.log(`Running ${fetchJobs.length} fetch + ${zodJobs.length} zod generations in parallel...`)
} else {
    console.log(`Running ${fetchJobs.length} orval generations in parallel...`)
}
console.log('')

// Run all orval generations in parallel (in-process, no subprocess overhead)
const results = await runOrvalParallel(allJobs.map((j) => ({ config: j.config, label: `${j.label}:${j.kind}` })))

// Report results and collect output dirs for formatting
const outputDirs = []
for (let i = 0; i < results.length; i++) {
    const result = results[i]
    const job = allJobs[i]
    if (result.status === 'fulfilled') {
        if (job.kind === 'zod') {
            const zodFile = path.join(job.outputDir, 'api.zod.ts')
            fixNullDefaults(zodFile)
            annotatePureZodExports(zodFile)
        }
        console.log(`   ✓ ${job.label}:${job.kind} → ${path.relative(repoRoot, job.outputDir)}`)
        if (!outputDirs.includes(job.outputDir)) {
            outputDirs.push(job.outputDir)
        }
        if (job.kind === 'fetch') {
            generated++
        }
    } else {
        console.error(`   ✗ ${job.label}:${job.kind}: ${result.reason?.message || result.reason}`)
        failed++
    }
}

// Run oxfmt once on all generated files
if (outputDirs.length > 0) {
    console.log('')
    console.log('Formatting generated files...')
    const globs = outputDirs.join(' ')
    execSync(`pnpm exec oxfmt ${globs}`, { stdio: 'pipe', cwd: repoRoot })
    console.log('   ✓ Formatted')
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
