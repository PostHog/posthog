// Diff `frontend/src/queries/schema.json` between base and HEAD, then map
// the changed top-level definitions back to the products that import them
// from `posthog.schema`. Used by turbo-discover.js to narrow the product
// matrix on PRs where only schema.json changes.
//
// Returns one of three kinds:
//   - 'additive'   only new definitions added → no products need re-testing
//                  for the schema change alone
//   - 'impacting'  some definitions modified or removed → return the union
//                  of products that import any of them
//   - 'fallback'   couldn't read or parse base schema → caller should treat
//                  as legacy (test everything)

const { execFileSync } = require('child_process')
const fs = require('fs')
const path = require('path')

const SCHEMA_PATH = 'frontend/src/queries/schema.json'
const PRODUCTS_ROOT = 'products'
const IMPORT_RE = /from\s+posthog\.schema\s+import\s+(\([\s\S]*?\)|[^\n]+)/g

function readHeadSchema(schemaPath = SCHEMA_PATH) {
    return fs.readFileSync(schemaPath, 'utf-8')
}

function readBaseSchema(scmBase, schemaPath = SCHEMA_PATH) {
    if (!scmBase) {
        return null
    }
    try {
        return execFileSync('git', ['show', `${scmBase}:${schemaPath}`], {
            encoding: 'utf-8',
            stdio: ['pipe', 'pipe', 'pipe'],
            maxBuffer: 50 * 1024 * 1024,
        })
    } catch {
        return null
    }
}

function diffDefinitions(baseRaw, headRaw) {
    const base = JSON.parse(baseRaw)
    const head = JSON.parse(headRaw)
    const baseDefs = base.definitions || {}
    const headDefs = head.definitions || {}
    const added = []
    const removed = []
    const modified = []
    for (const key of Object.keys(headDefs)) {
        if (!(key in baseDefs)) {
            added.push(key)
        } else if (JSON.stringify(baseDefs[key]) !== JSON.stringify(headDefs[key])) {
            modified.push(key)
        }
    }
    for (const key of Object.keys(baseDefs)) {
        if (!(key in headDefs)) {
            removed.push(key)
        }
    }
    return { added, removed, modified }
}

function extractImports(source) {
    const types = []
    let m
    IMPORT_RE.lastIndex = 0
    while ((m = IMPORT_RE.exec(source)) !== null) {
        let raw = m[1].trim()
        if (raw.startsWith('(')) {
            raw = raw.slice(1, -1)
        }
        raw = raw.replace(/#[^\n]*/g, '')
        for (const part of raw.split(',')) {
            const name = part.trim().split(/\s+as\s+/)[0].trim()
            if (name) {
                types.push(name)
            }
        }
    }
    return types
}

function walkPyFiles(dir, out = []) {
    let entries
    try {
        entries = fs.readdirSync(dir, { withFileTypes: true })
    } catch {
        return out
    }
    for (const entry of entries) {
        const full = path.join(dir, entry.name)
        if (entry.isDirectory()) {
            walkPyFiles(full, out)
        } else if (entry.isFile() && full.endsWith('.py')) {
            out.push(full)
        }
    }
    return out
}

// products/<dir>/... → product matrix name (hyphenated to match @posthog/products-<name>)
function productFromPath(filePath, productsRoot = PRODUCTS_ROOT) {
    const rel = path.relative(productsRoot, filePath)
    const [first] = rel.split(path.sep)
    if (!first || first.startsWith('..')) {
        return null
    }
    return first.replace(/_/g, '-')
}

function buildImportMap(productsRoot = PRODUCTS_ROOT) {
    const typeToProducts = new Map()
    const files = walkPyFiles(productsRoot)
    for (const file of files) {
        const product = productFromPath(file, productsRoot)
        if (!product) {
            continue
        }
        let source
        try {
            source = fs.readFileSync(file, 'utf-8')
        } catch {
            continue
        }
        if (!source.includes('posthog.schema')) {
            continue
        }
        for (const typeName of extractImports(source)) {
            let set = typeToProducts.get(typeName)
            if (!set) {
                set = new Set()
                typeToProducts.set(typeName, set)
            }
            set.add(product)
        }
    }
    return typeToProducts
}

function affectedProductsFor(changedTypes, importMap) {
    const products = new Set()
    for (const typeName of changedTypes) {
        const set = importMap.get(typeName)
        if (set) {
            for (const product of set) {
                products.add(product)
            }
        }
    }
    return [...products].sort()
}

function analyzeSchemaImpact({ scmBase, schemaPath = SCHEMA_PATH, productsRoot = PRODUCTS_ROOT } = {}) {
    const headRaw = (() => {
        try {
            return readHeadSchema(schemaPath)
        } catch {
            return null
        }
    })()
    if (headRaw === null) {
        return { kind: 'fallback', reason: 'head-schema-missing', affectedProducts: [] }
    }
    const baseRaw = readBaseSchema(scmBase, schemaPath)
    if (baseRaw === null) {
        return { kind: 'fallback', reason: 'base-schema-unavailable', affectedProducts: [] }
    }
    let diff
    try {
        diff = diffDefinitions(baseRaw, headRaw)
    } catch (e) {
        return { kind: 'fallback', reason: `parse-error: ${e.message}`, affectedProducts: [] }
    }
    const impacting = [...diff.modified, ...diff.removed]
    if (impacting.length === 0) {
        return {
            kind: 'additive',
            affectedProducts: [],
            counts: { added: diff.added.length, modified: 0, removed: 0 },
        }
    }
    const importMap = buildImportMap(productsRoot)
    const affectedProducts = affectedProductsFor(impacting, importMap)
    return {
        kind: 'impacting',
        affectedProducts,
        changedTypes: impacting,
        counts: { added: diff.added.length, modified: diff.modified.length, removed: diff.removed.length },
    }
}

module.exports = {
    analyzeSchemaImpact,
    diffDefinitions,
    extractImports,
    buildImportMap,
    affectedProductsFor,
    productFromPath,
}
