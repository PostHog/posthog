// Diff `frontend/src/queries/schema.json` between base and HEAD, then map the
// changed definitions to the products that depend on them (resolved from the
// AST by schema_usage_scan.py). Used by turbo-discover.js to narrow the product
// matrix on schema-only PRs.
//
// Returns 'additive' (only new defs — nothing to retest), 'impacting' (union of
// affected products), or 'fallback' (base schema unreadable or scanner failed —
// caller tests everything).

const { execFileSync } = require('child_process')
const fs = require('fs')
const path = require('path')

const SCHEMA_PATH = 'frontend/src/queries/schema.json'
const PRODUCTS_ROOT = 'products'
const SCAN_SCRIPT = path.join(__dirname, 'schema_usage_scan.py')
// Sentinel key: products with unresolvable usage, unioned in on any change.
const WILDCARD = '*'

function readHeadSchema(schemaPath = SCHEMA_PATH) {
    try {
        return fs.readFileSync(schemaPath, 'utf-8')
    } catch {
        return null
    }
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

// Map<type, Set<product>> (incl. WILDCARD) from the AST scanner. Throws if no
// Python is available or the scan fails; analyzeSchemaImpact turns that into a
// conservative 'fallback'.
function buildImportMap(productsRoot = PRODUCTS_ROOT) {
    const candidates = process.env.PYTHON ? [process.env.PYTHON] : ['python3', 'python']
    let raw
    let lastErr
    for (const bin of candidates) {
        try {
            raw = execFileSync(bin, [SCAN_SCRIPT, productsRoot], {
                encoding: 'utf-8',
                stdio: ['pipe', 'pipe', 'pipe'],
                maxBuffer: 64 * 1024 * 1024,
            })
            break
        } catch (e) {
            lastErr = e
        }
    }
    if (raw === undefined) {
        throw lastErr || new Error('schema_usage_scan.py could not be executed')
    }
    const map = new Map()
    for (const [typeName, products] of Object.entries(JSON.parse(raw))) {
        map.set(typeName, new Set(products))
    }
    return map
}

function affectedProductsFor(changedTypes, importMap) {
    const products = new Set()
    const collect = (key) => {
        for (const product of importMap.get(key) || []) {
            products.add(product)
        }
    }
    for (const typeName of changedTypes) {
        collect(typeName)
    }
    // any change also pulls in products with unresolvable usage
    if (changedTypes.length > 0) {
        collect(WILDCARD)
    }
    return [...products].sort()
}

function analyzeSchemaImpact({ scmBase, schemaPath = SCHEMA_PATH, productsRoot = PRODUCTS_ROOT } = {}) {
    const fallback = (reason) => ({ kind: 'fallback', reason, affectedProducts: [] })

    const headRaw = readHeadSchema(schemaPath)
    if (headRaw === null) {
        return fallback('head-schema-missing')
    }
    const baseRaw = readBaseSchema(scmBase, schemaPath)
    if (baseRaw === null) {
        return fallback('base-schema-unavailable')
    }
    let diff
    try {
        diff = diffDefinitions(baseRaw, headRaw)
    } catch (e) {
        return fallback(`parse-error: ${e.message}`)
    }
    const impacting = [...diff.modified, ...diff.removed]
    if (impacting.length === 0) {
        return {
            kind: 'additive',
            affectedProducts: [],
            counts: { added: diff.added.length, modified: 0, removed: 0 },
        }
    }
    let importMap
    try {
        importMap = buildImportMap(productsRoot)
    } catch (e) {
        return fallback(`scanner-failed: ${e.message}`)
    }
    const affectedProducts = affectedProductsFor(impacting, importMap)
    const wildcardProducts = [...(importMap.get(WILDCARD) || [])].sort()
    return {
        kind: 'impacting',
        affectedProducts,
        wildcardProducts,
        changedTypes: impacting,
        counts: { added: diff.added.length, modified: diff.modified.length, removed: diff.removed.length },
    }
}

module.exports = {
    analyzeSchemaImpact,
    diffDefinitions,
    buildImportMap,
    affectedProductsFor,
    readBaseSchema,
}
