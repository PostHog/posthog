#!/usr/bin/env node
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

function getOutputDirForTag(tag, productFolders) {
    if (tag === 'core') {
        return path.resolve(frontendRoot, 'src', 'types', 'api')
    }
    // Normalize tag: convert hyphens to underscores to match folder names
    const normalizedTag = tag.replace(/-/g, '_')
    if (productFolders.has(normalizedTag)) {
        return path.resolve(productsDir, normalizedTag, 'frontend', 'types', 'api')
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

    const outputFile = path.join(outputDir, 'types.ts')

    // Create orval config for this schema - single file mode for types only
    const configFile = path.join(tmpDir, 'orval.config.mjs')
    const config = `
import { defineConfig } from 'orval';
export default defineConfig({
  api: {
    input: '${schemaFile}',
    output: {
      target: '${outputFile}',
      mode: 'single',
      client: 'fetch',
    },
  },
});
`
    fs.writeFileSync(configFile, config)

    execSync(`pnpm exec orval --config "${configFile}"`, {
        stdio: 'inherit',
        cwd: repoRoot,
    })

    // Add eslint-disable header to generated file
    const content = fs.readFileSync(outputFile, 'utf8')
    const header = '/* eslint-disable */\n'
    if (!content.startsWith(header)) {
        fs.writeFileSync(outputFile, header + content)
    }
}

// Main execution
const schema = JSON.parse(fs.readFileSync(schemaPath, 'utf8'))
const productFolders = discoverProductFolders()
const groupedSchemas = buildGroupedSchemasByTag(schema)
const tmpDir = createTempDir()

let generated = 0
let failed = 0
for (const [tag, groupedSchema] of groupedSchemas.entries()) {
    const outputDir = getOutputDirForTag(tag, productFolders)
    if (!outputDir) {
        continue
    }

    const tempFile = path.join(tmpDir, `${tag.replace(/[^a-zA-Z0-9_-]/g, '_')}.json`)
    fs.writeFileSync(tempFile, JSON.stringify(groupedSchema, null, 2))

    try {
        generateTypesForSchema(tempFile, outputDir, tag, tmpDir)
        generated++
    } catch (err) {
        console.error(`  ⚠️  Failed to generate types for "${tag}": ${err.message}`)
        failed++
    }
}

// Cleanup temp dir
fs.rmSync(tmpDir, { recursive: true, force: true })
