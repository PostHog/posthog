// Generate services/mcp/.../app-url-manifest.json — the canonical route table the MCP `generate-app-url`
// tool resolves entity links from, so agents never hand-build (and mis-slug) PostHog URLs.
//
// The complete source of truth is the merged `urls` object the frontend ships:
// `{ ...productUrls, <~80 builders defined directly in scenes/urls.ts> }`. We can't import it in a
// plain Node script — its transitive graph pulls monaco, `?raw` assets, scss, dayjs, etc., which only
// the full frontend build (or jest's moduleNameMapper) resolves. So instead we extract each builder's
// *source* via the TypeScript compiler (no app import), strip types, and reconstruct it in a tiny
// sandbox that provides the few things builders touch (`combineUrl`, `encodeURIComponent`, ...). Then we
// recover each route template by invoking the real builder with `:name` sentinels — the same trick
// urls.ts itself uses (`href(':id')`) — so combineUrl/ternaries/encoding are handled by the shipped code.
//
// Usage:
//   node bin/build-app-url-manifest.mjs           # write the manifest
//   node bin/build-app-url-manifest.mjs --check    # exit 1 if the committed manifest is stale

import * as ps from 'child_process'
import fs from 'fs'
import { combineUrl } from 'kea-router'
import path from 'path'
import ts from 'typescript'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const FRONTEND = path.resolve(__dirname, '..')
const REPO = path.resolve(FRONTEND, '..')
const URLS_FILE = path.join(FRONTEND, 'src/scenes/urls.ts')
const PRODUCTS_DIR = path.join(REPO, 'products')
const OUT_FILE = path.join(REPO, 'services/mcp/src/tools/links/app-url-manifest.json')

// First path segments that never get a `/project/:id` prefix. Mirrors `pathsWithoutProjectId` in
// frontend/src/lib/utils/router-utils.ts — keep in sync there.
const PATHS_WITHOUT_PROJECT_ID = new Set([
    'api',
    'me',
    'instance',
    'organization',
    'preflight',
    'login',
    'signup',
    'create-organization',
    'account',
    'oauth',
    'shared',
    'embedded',
    'interview',
    'cli',
    'render_query',
])
const isProjectScoped = (template) => !PATHS_WITHOUT_PROJECT_ID.has(template.split('/')[1] ?? '')

// `urls` helpers that build prefixes/origins rather than linkable destinations.
const EXCLUDED_HELPERS = new Set(['absolute', 'default', 'project', 'currentProject', 'newTab'])

const sentinel = (name) => `:${name}`

// ---- sandbox: turn extracted builder source into callable functions without importing the app ----

function buildSandboxScope() {
    // App-specific bindings builders reference; everything else (Boolean, Math, JSON, …) comes from
    // the real Node globals via the get trap below.
    const real = {
        combineUrl,
        // Only one builder uses toParams (experiments); a faithful-enough query serializer.
        toParams: (obj = {}) =>
            Object.entries(obj)
                .filter(([, v]) => v !== undefined && v !== null)
                .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
                .join('&'),
        getCurrentTeamId: () => {
            throw new Error('no team in codegen')
        },
        urls: {},
    }
    // Stand-in for unknown app identifiers — enums (`ActivityTab.ExploreEvents`) and imported type
    // guards (`isHogQLQuery(query)`). Callable and indexable, always returning undefined, so an
    // enum-defaulted param renders as `undefined` (the probe then supplies a sentinel, e.g.
    // `activity` -> `/activity/{tab}`) and a guard call is simply falsy instead of throwing.
    const stub = new Proxy(function () {}, { get: () => undefined, apply: () => undefined, construct: () => ({}) })
    // `has: () => true` makes `with` route every identifier here; resolve known bindings, then real
    // globals, then the stub.
    return new Proxy(real, {
        has: () => true,
        get: (t, k) => (k in t ? t[k] : typeof k === 'string' && k in globalThis ? globalThis[k] : stub),
    })
}

function stripTypes(objLiteralText) {
    const out = ts.transpile(`(${objLiteralText})`, {
        target: ts.ScriptTarget.ESNext,
        module: ts.ModuleKind.None,
        alwaysStrict: false,
        removeComments: true,
    })
    // ts may emit a leading "use strict" directive, which both forbids `with` and would become the
    // return value — strip it and any trailing semicolon.
    return out.replace(/^\s*["']use strict["'];?\s*/, '').replace(/;?\s*$/, '')
}

function evalObject(objLiteralText, scope) {
    const js = stripTypes(objLiteralText)
    // eslint-disable-next-line no-new-func -- build-time codegen over first-party source
    return new Function('__scope', `with (__scope) { return (${js}) }`)(scope)
}

// ---- extract the `urls: {}` object literal text from a source file ----

function readUrlsObjectText(file, { fromManifest }) {
    const src = fs.readFileSync(file, 'utf8')
    const sf = ts.createSourceFile(file, src, ts.ScriptTarget.Latest, true)
    let text = null
    sf.forEachChild(function walk(node) {
        if (text) {
            return
        }
        if (
            fromManifest &&
            ts.isPropertyAssignment(node) &&
            node.name.getText(sf) === 'urls' &&
            ts.isObjectLiteralExpression(node.initializer)
        ) {
            text = node.initializer.getText(sf)
        } else if (
            !fromManifest &&
            ts.isVariableDeclaration(node) &&
            node.name.getText(sf) === 'urls' &&
            node.initializer &&
            ts.isObjectLiteralExpression(node.initializer)
        ) {
            // Drop the `...productUrls` spread — those builders come from the product manifests.
            const props = node.initializer.properties.filter((p) => !ts.isSpreadAssignment(p))
            text = `{${props.map((p) => p.getText(sf)).join(',\n')}}`
        } else {
            ts.forEachChild(node, walk)
        }
    })
    return text
}

function collectUrls() {
    const scope = buildSandboxScope()

    const productUrls = {}
    for (const product of fs.readdirSync(PRODUCTS_DIR).sort()) {
        const manifest = path.join(PRODUCTS_DIR, product, 'manifest.tsx')
        if (!fs.existsSync(manifest)) {
            continue
        }
        const text = readUrlsObjectText(manifest, { fromManifest: true })
        if (text) {
            Object.assign(productUrls, evalObject(text, scope))
        }
    }

    const directText = readUrlsObjectText(URLS_FILE, { fromManifest: false })
    const direct = evalObject(directText, scope)

    const merged = { ...productUrls, ...direct }
    // Builders reference `urls.*` (e.g. `embedded` -> `urls.shared`); resolve self-refs to the merged set.
    scope.urls = merged
    return merged
}

// ---- probe each builder for its route template (ported from the runtime generator) ----

function parenContents(src) {
    const start = src.indexOf('(')
    if (start === -1) {
        return null
    }
    let depth = 0
    for (let i = start; i < src.length; i++) {
        const ch = src[i]
        if (ch === '(') {
            depth++
        } else if (ch === ')') {
            depth--
            if (depth === 0) {
                return src.slice(start + 1, i)
            }
        }
    }
    return null
}

function splitTopLevel(input) {
    const parts = []
    let depth = 0
    let current = ''
    for (const ch of input) {
        if (ch === '(' || ch === '[' || ch === '{') {
            depth++
        } else if (ch === ')' || ch === ']' || ch === '}') {
            depth--
        }
        if (ch === ',' && depth === 0) {
            parts.push(current)
            current = ''
        } else {
            current += ch
        }
    }
    if (current.trim()) {
        parts.push(current)
    }
    return parts
}

function readSignature(fn) {
    const src = fn.toString().trim()
    const single = src.match(/^(?:async\s+)?([A-Za-z_$][\w$]*)\s*=>/)
    if (single) {
        return { kind: 'positional', names: [single[1]] }
    }
    const paramStr = parenContents(src)
    if (paramStr === null) {
        return null
    }
    const trimmed = paramStr.trim()
    if (trimmed === '') {
        return { kind: 'positional', names: [] }
    }
    if (trimmed.startsWith('{')) {
        return { kind: 'object', names: [] }
    }
    const names = splitTopLevel(trimmed)
        .map((part) => part.trim().split('=')[0].trim())
        .filter(Boolean)
    return { kind: 'positional', names }
}

// Invoke with the fewest sentinel args that yield a clean path — drops optional trailing params and
// hits guarded default branches (`replay()` -> `/replay/home`) instead of erroring on a sentinel.
function probeBuilder(fn, signature) {
    const maxArgs = signature.kind === 'object' ? 0 : signature.names.length
    for (let count = 0; count <= maxArgs; count++) {
        const args = signature.kind === 'object' ? [{}] : signature.names.slice(0, count).map(sentinel)
        let raw
        try {
            raw = fn(...args)
        } catch {
            continue
        }
        if (typeof raw !== 'string') {
            continue
        }
        const pathOnly = raw.split('?')[0].split('#')[0]
        if (
            !pathOnly.startsWith('/') ||
            pathOnly === '/' ||
            pathOnly.includes('undefined') ||
            pathOnly.includes('null')
        ) {
            continue
        }
        return pathOnly
    }
    return null
}

function replaceSentinels(pathOnly, paramNames) {
    let template = pathOnly
    const found = new Set()
    for (const name of [...paramNames].sort((a, b) => b.length - a.length)) {
        const encoded = encodeURIComponent(sentinel(name))
        const plain = sentinel(name)
        const before = template
        template = template.split(encoded).join(`{${name}}`).split(plain).join(`{${name}}`)
        if (template !== before) {
            found.add(name)
        }
    }
    return { template, params: paramNames.filter((name) => found.has(name)) }
}

function buildManifest(urls) {
    const manifest = {}
    const excluded = []
    const baseOnly = []
    for (const name of Object.keys(urls).sort()) {
        if (EXCLUDED_HELPERS.has(name)) {
            excluded.push({ name, reason: 'structural helper' })
            continue
        }
        const fn = urls[name]
        if (typeof fn !== 'function') {
            excluded.push({ name, reason: 'not a function' })
            continue
        }
        const signature = readSignature(fn)
        if (!signature) {
            excluded.push({ name, reason: 'could not parse signature' })
            continue
        }
        const probePath = probeBuilder(fn, signature)
        if (!probePath) {
            excluded.push({ name, reason: 'no clean path' })
            continue
        }
        // Map against the full signature so a sentinel-valued default (`accountConnected`) still resolves.
        const { template, params } = replaceSentinels(probePath, signature.names)
        manifest[name] = { template, params, scope: isProjectScoped(template) ? 'project' : 'global' }
        if ((signature.kind === 'object' || signature.names.length > 0) && params.length === 0) {
            baseOnly.push(name)
        }
    }
    return { manifest, excluded, baseOnly }
}

// Format with oxfmt (same as build-products.mjs) so the written file matches the repo's committed
// style — so `build:products && git diff --exit-code` in CI catches drift instead of false-positiving
// on formatting. oxfmt resolves on PATH under `pnpm` (node_modules/.bin).
function renderFormatted(manifest) {
    const tmp = path.join(FRONTEND, 'tmp')
    fs.mkdirSync(tmp, { recursive: true })
    const tmpFile = path.join(tmp, 'app-url-manifest.json')
    fs.writeFileSync(tmpFile, JSON.stringify(manifest, null, 4) + '\n')
    ps.execFileSync('oxfmt', [tmpFile])
    const formatted = fs.readFileSync(tmpFile, 'utf8')
    fs.rmSync(tmpFile, { force: true })
    return formatted
}

// ---- main ----

const { manifest, excluded, baseOnly } = buildManifest(collectUrls())
const formatted = renderFormatted(manifest)

if (process.argv.includes('--check')) {
    const committed = fs.existsSync(OUT_FILE) ? fs.readFileSync(OUT_FILE, 'utf8') : ''
    if (committed !== formatted) {
        process.stderr.write('app-url-manifest.json is stale. Run `pnpm --filter=@posthog/frontend build:app-urls`.\n')
        process.exit(1)
    }
    process.stdout.write(`app-url-manifest.json up to date (${Object.keys(manifest).length} entries).\n`)
} else {
    fs.writeFileSync(OUT_FILE, formatted)
    process.stdout.write(
        `Wrote ${Object.keys(manifest).length} entries to ${path.relative(REPO, OUT_FILE)} ` +
            `(${baseOnly.length} base-only, ${excluded.length} excluded).\n`
    )
}
