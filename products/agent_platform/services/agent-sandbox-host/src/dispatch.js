#!/usr/bin/env node
/*
 * Per-invoke dispatcher. Invoked by the runner-side DockerSandbox via
 * `docker exec <container> node /sandbox/dispatch.js /workdir/request.json
 * /workdir/response.json`. Reads the request, loads the requested tool's
 * `compiled.js` from `/workdir/tools/<id>/compiled.js`, looks up the action,
 * runs it with the supplied args + a minimal `ctx`, writes the response.
 *
 * Wire format:
 *   request.json : { "toolId": string, "action": string, "args": unknown, "timeoutMs"?: number }
 *   response.json:
 *     { "ok": true, "result": unknown }
 *   | { "ok": false, "error": { "code": string, "message": string } }
 *
 * Compiled-tool contract:
 *   module.exports = {
 *     id: "<tool-id>",
 *     actions: {
 *       <name>: (args, ctx) => any | Promise<any>
 *     }
 *   }
 *
 * `ctx` exposes:
 *   - secrets.ref(name)  → opaque per-session nonce string. The raw secret
 *     never enters the sandbox, and the sandbox has no outbound network
 *     (block_network / --network=none), so a nonce cannot be exfiltrated.
 *     NOTE: runner-side nonce→value substitution at egress is not yet wired —
 *     a returned nonce won't resolve to the real secret today. Tools should
 *     return values for the runner to act on, not attempt their own egress.
 *   - log(level, msg, meta?)
 *
 * Nonces are read from /workdir/nonces.json once at startup. Re-read on each
 * invoke so the runner can rotate them across turns without restarting the
 * sandbox (cheap — small file).
 */

'use strict'

const fs = require('node:fs')
const path = require('node:path')
const { performance } = require('node:perf_hooks')

const TOOLS_DIR = process.env.SANDBOX_TOOLS_DIR || '/workdir/tools'
const NONCES_PATH = process.env.SANDBOX_NONCES_PATH || '/workdir/nonces.json'

function readJson(p) {
    return JSON.parse(fs.readFileSync(p, 'utf-8'))
}

function writeJson(p, value) {
    fs.writeFileSync(p, JSON.stringify(value))
}

function loadNonces() {
    try {
        return readJson(NONCES_PATH)
    } catch {
        return {}
    }
}

function loadTool(toolId) {
    const compiledPath = path.join(TOOLS_DIR, toolId, 'compiled.js')
    if (!fs.existsSync(compiledPath)) {
        throw Object.assign(new Error(`tool not found: ${toolId}`), { code: 'tool_not_found' })
    }
    // Clear require cache so a re-published bundle is picked up — sandboxes
    // are per-session so cache reuse is fine within one session.
    delete require.cache[require.resolve(compiledPath)]
    return require(compiledPath)
}

function buildContext(nonces) {
    return {
        secrets: {
            ref: (name) => {
                if (!(name in nonces)) {
                    throw new Error(`secret not provisioned: ${name}`)
                }
                return nonces[name]
            },
        },
        log: (level, msg, meta) => {
            // Sandbox logs go to stderr so the container collector can pick them up.
            // The runner doesn't read them today; this is observability for ops.
            const entry = { level, msg, meta: meta ?? null, ts: new Date().toISOString() }
            process.stderr.write(JSON.stringify(entry) + '\n')
        },
    }
}

async function withTimeout(promise, timeoutMs) {
    if (!timeoutMs || timeoutMs <= 0) {
        return promise
    }
    let timer
    try {
        return await Promise.race([
            promise,
            new Promise((_resolve, reject) => {
                timer = setTimeout(
                    () => reject(Object.assign(new Error('tool timeout'), { code: 'timeout' })),
                    timeoutMs
                )
            }),
        ])
    } finally {
        clearTimeout(timer)
    }
}

async function dispatch(request) {
    const tool = loadTool(request.toolId)
    const action = (tool.actions || {})[request.action]
    if (typeof action !== 'function') {
        throw Object.assign(new Error(`action not found: ${request.action}`), { code: 'action_not_found' })
    }
    const ctx = buildContext(loadNonces())
    const t0 = performance.now()
    const result = await withTimeout(Promise.resolve(action(request.args, ctx)), request.timeoutMs)
    const ms = Math.round(performance.now() - t0)
    return { result, ms }
}

async function main() {
    const [reqPath, resPath] = process.argv.slice(2)
    if (!reqPath || !resPath) {
        process.stderr.write('usage: dispatch.js <request.json> <response.json>\n')
        process.exit(2)
    }
    let response
    try {
        const request = readJson(reqPath)
        const { result } = await dispatch(request)
        response = { ok: true, result }
    } catch (err) {
        response = {
            ok: false,
            error: {
                code: err.code || 'tool_invoke_failed',
                message: err.message || String(err),
            },
        }
    }
    writeJson(resPath, response)
}

if (require.main === module) {
    main().catch((err) => {
        process.stderr.write(`dispatch fatal: ${err.stack || err.message}\n`)
        process.exit(1)
    })
}

module.exports = { dispatch, loadTool, buildContext, withTimeout }
