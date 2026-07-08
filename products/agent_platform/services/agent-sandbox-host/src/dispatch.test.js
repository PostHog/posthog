'use strict'

/*
 * Unit tests for dispatch.js. Uses node:test so the host package stays
 * dependency-free (matches the lean image — no vitest in the container).
 * Set SANDBOX_TOOLS_DIR / SANDBOX_NONCES_PATH to per-test temp dirs so
 * tests don't collide with /workdir on a dev machine.
 */

const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

function tempdir() {
    return fs.mkdtempSync(path.join(os.tmpdir(), 'sandbox-host-test-'))
}

function setupToolsDir() {
    const dir = tempdir()
    process.env.SANDBOX_TOOLS_DIR = path.join(dir, 'tools')
    process.env.SANDBOX_NONCES_PATH = path.join(dir, 'nonces.json')
    fs.mkdirSync(process.env.SANDBOX_TOOLS_DIR, { recursive: true })
    return dir
}

function writeTool(toolId, source) {
    const toolDir = path.join(process.env.SANDBOX_TOOLS_DIR, toolId)
    fs.mkdirSync(toolDir, { recursive: true })
    fs.writeFileSync(path.join(toolDir, 'compiled.js'), source)
}

function freshRequire() {
    // dispatch.js caches require results; bypass for the unit tests so each
    // case starts clean.
    delete require.cache[require.resolve('./dispatch.js')]
    return require('./dispatch.js')
}

test('dispatch returns the action result for a known tool + action', async () => {
    setupToolsDir()
    writeTool('echo', `module.exports = { id: "echo", actions: { default: (args) => ({ got: args }) } }`)
    const { dispatch } = freshRequire()
    const out = await dispatch({ toolId: 'echo', action: 'default', args: { hi: 'world' } })
    assert.deepEqual(out.result, { got: { hi: 'world' } })
})

test('dispatch unwraps an esbuild-CJS default export (typed-pipeline compiled.js)', async () => {
    setupToolsDir()
    // This fixture IS the repo's esbuild output: the janitor's typed pipeline
    // mandates `export default {...}` source and compiles with esbuild
    // format:"cjs" (loader:"ts", target:"node20"), which exposes the tool
    // object as `.default` via a __toCommonJS getter on module.exports — not
    // a bare `module.exports = {...}` like the fixtures above.
    writeTool(
        'typed-echo',
        `var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);
var stdin_exports = {};
__export(stdin_exports, {
  default: () => stdin_default
});
module.exports = __toCommonJS(stdin_exports);
var stdin_default = { id: "typed-echo", actions: { default: async (args) => ({ ok: true, echo: args.x }) } };
`
    )
    const { dispatch } = freshRequire()
    const out = await dispatch({ toolId: 'typed-echo', action: 'default', args: { x: 42 } })
    assert.deepEqual(out.result, { ok: true, echo: 42 })
})

test('dispatch surfaces a tool-not-found error code', async () => {
    setupToolsDir()
    const { dispatch } = freshRequire()
    try {
        await dispatch({ toolId: 'nope', action: 'default', args: {} })
        assert.fail('expected throw')
    } catch (err) {
        assert.equal(err.code, 'tool_not_found')
    }
})

test('dispatch surfaces an action-not-found error code', async () => {
    setupToolsDir()
    writeTool('one-action', `module.exports = { id: "one-action", actions: { only: () => 1 } }`)
    const { dispatch } = freshRequire()
    try {
        await dispatch({ toolId: 'one-action', action: 'missing', args: {} })
        assert.fail('expected throw')
    } catch (err) {
        assert.equal(err.code, 'action_not_found')
    }
})

test('dispatch propagates errors thrown by the tool action', async () => {
    setupToolsDir()
    writeTool('thrower', `module.exports = { id: "thrower", actions: { default: () => { throw new Error("boom"); } } }`)
    const { dispatch } = freshRequire()
    try {
        await dispatch({ toolId: 'thrower', action: 'default', args: {} })
        assert.fail('expected throw')
    } catch (err) {
        assert.match(err.message, /boom/)
    }
})

test('dispatch enforces timeoutMs via withTimeout', async () => {
    setupToolsDir()
    writeTool(
        'slow',
        `module.exports = { id: "slow", actions: { default: () => new Promise((r) => setTimeout(r, 200)) } }`
    )
    const { dispatch } = freshRequire()
    try {
        await dispatch({ toolId: 'slow', action: 'default', args: {}, timeoutMs: 20 })
        assert.fail('expected timeout')
    } catch (err) {
        assert.equal(err.code, 'timeout')
    }
})

test('ctx.secrets.ref returns the nonce when configured', async () => {
    const dir = setupToolsDir()
    fs.writeFileSync(path.join(dir, 'nonces.json'), JSON.stringify({ ACME_KEY: 'nonce_abc' }))
    writeTool(
        'secret-user',
        `module.exports = {
            id: "secret-user",
            actions: { default: (_args, ctx) => ({ token: ctx.secrets.ref("ACME_KEY") }) },
        }`
    )
    const { dispatch } = freshRequire()
    const out = await dispatch({ toolId: 'secret-user', action: 'default', args: {} })
    assert.deepEqual(out.result, { token: 'nonce_abc' })
})

test('ctx.secrets.ref throws on a name not in nonces.json', async () => {
    setupToolsDir()
    // No nonces file written.
    writeTool(
        'secret-user',
        `module.exports = {
            id: "secret-user",
            actions: { default: (_args, ctx) => ctx.secrets.ref("NOT_THERE") },
        }`
    )
    const { dispatch } = freshRequire()
    try {
        await dispatch({ toolId: 'secret-user', action: 'default', args: {} })
        assert.fail('expected throw')
    } catch (err) {
        assert.match(err.message, /secret not provisioned/)
    }
})
