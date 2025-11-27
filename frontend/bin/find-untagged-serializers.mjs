#!/usr/bin/env node
/* eslint-disable no-console */
/**
 * Find serializers that might need @extend_schema tags.
 *
 * Looks at manually-written TypeScript types and finds corresponding
 * Django serializers that aren't yet tagged for OpenAPI generation.
 */
import { execSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const frontendRoot = path.resolve(__dirname, '..')
const repoRoot = path.resolve(frontendRoot, '..')

// Files containing manual types that might correspond to API responses
const MANUAL_TYPE_FILES = ['frontend/src/types.ts', 'frontend/src/lib/components/Errors/types.ts']

// Extract type names from TypeScript files
function extractTypeNames(filePath) {
    const fullPath = path.resolve(repoRoot, filePath)
    if (!fs.existsSync(fullPath)) {
        return []
    }
    const content = fs.readFileSync(fullPath, 'utf8')
    const matches = [...content.matchAll(/^export (?:interface|type) (\w+)/gm)]
    return matches.map((m) => m[1])
}

// Find serializers in Python code
function findSerializers() {
    try {
        const result = execSync(
            `rg "class (\\w+)Serializer.*:" posthog/ products/ ee/ --glob "*.py" -o --no-heading 2>/dev/null || true`,
            { encoding: 'utf8', cwd: repoRoot }
        )
        const serializers = new Map()
        for (const line of result.trim().split('\n')) {
            if (!line) {
                continue
            }
            const match = line.match(/^(.+):class (\w+)Serializer/)
            if (match) {
                const [, filePath, name] = match
                serializers.set(name, filePath)
            }
        }
        return serializers
    } catch {
        return new Map()
    }
}

// Check if a file has @extend_schema with tags
function hasExtendSchemaTags(filePath) {
    try {
        const fullPath = path.resolve(repoRoot, filePath)
        const content = fs.readFileSync(fullPath, 'utf8')
        return content.includes('@extend_schema') && content.includes('tags=')
    } catch {
        return false
    }
}

// Normalize type name to match serializer naming
function normalizeTypeName(name) {
    // Remove common suffixes
    return name
        .replace(/Type$/, '')
        .replace(/Response$/, '')
        .replace(/Basic$/, '')
}

// Main
console.log('🔍 Finding manual types that might need serializer tags...\n')

const allTypeNames = new Set()
for (const file of MANUAL_TYPE_FILES) {
    const names = extractTypeNames(file)
    for (const name of names) {
        allTypeNames.add(name)
    }
}

console.log(`   Found ${allTypeNames.size} manual types in ${MANUAL_TYPE_FILES.length} files`)

const serializers = findSerializers()
console.log(`   Found ${serializers.size} serializers in Python code\n`)

// Find matches
const matches = []
for (const typeName of allTypeNames) {
    const normalized = normalizeTypeName(typeName)
    if (serializers.has(normalized)) {
        const serializerFile = serializers.get(normalized)
        const hasTag = hasExtendSchemaTags(serializerFile)
        matches.push({
            typeName,
            serializerName: `${normalized}Serializer`,
            serializerFile,
            hasTag,
        })
    }
}

// Report
const untagged = matches.filter((m) => !m.hasTag)
const tagged = matches.filter((m) => m.hasTag)

if (untagged.length > 0) {
    console.log('⚠️  Serializers without @extend_schema tags (potential candidates):')
    for (const { typeName, serializerName, serializerFile } of untagged) {
        console.log(`   ${typeName} → ${serializerName}`)
        console.log(`      └─ ${serializerFile}`)
    }
    console.log('')
    console.log('   To enable type generation, add to the ViewSet:')
    console.log('   @extend_schema(tags=["your_product"])')
}

if (tagged.length > 0) {
    console.log('')
    console.log('✅ Serializers already tagged (types may be redundant):')
    for (const { typeName, serializerName, serializerFile } of tagged) {
        console.log(`   ${typeName} → ${serializerName}`)
        console.log(`      └─ ${serializerFile}`)
    }
}

if (matches.length === 0) {
    console.log('No direct matches found between manual types and serializers.')
    console.log('This might mean:')
    console.log('  - Types use different naming conventions')
    console.log('  - Types are for non-API data (UI state, etc.)')
}

console.log('')
console.log(`Summary: ${untagged.length} untagged, ${tagged.length} tagged`)
