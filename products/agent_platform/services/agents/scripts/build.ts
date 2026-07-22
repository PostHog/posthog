/**
 * Bundles the agent-platform runtime entrypoints into self-contained ESM
 * files under `dist/`. Mirrors services/mcp/scripts/build-hono.ts in shape
 * (single esbuild invocation, minimal externals, banner that shims `require`
 * for CJS deps like `pg`).
 *
 * Output layout (consumed by services/agents/Dockerfile):
 *   dist/ingress.mjs
 *   dist/runner.mjs
 *   dist/janitor.mjs
 *
 * Schema migrations are no longer bundled here — the agent_platform schema is
 * Django-owned (the `agent_platform` product DB), migrated by the
 * posthog-django `migrate_product_databases` job.
 */

import { build } from 'esbuild'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(HERE, '../../../../..')
const OUT_DIR = resolve(HERE, '..', 'dist')

const ENTRY_POINTS = {
    ingress: resolve(ROOT, 'products/agent_platform/services/agent-ingress/src/index.ts'),
    runner: resolve(ROOT, 'products/agent_platform/services/agent-runner/src/index.ts'),
    janitor: resolve(ROOT, 'products/agent_platform/services/agent-janitor/src/index.ts'),
}

await build({
    entryPoints: ENTRY_POINTS,
    bundle: true,
    platform: 'node',
    target: 'node24',
    format: 'esm',
    outdir: OUT_DIR,
    outExtension: { '.js': '.mjs' },
    sourcemap: true,
    // - `pg-native`: optional C addon, only loaded via `require('pg').native` which no service uses.
    //   Leave unresolved at bundle time to avoid dragging libpq into the runtime image.
    // - `node-rdkafka`: native binding (.node); cannot be inlined into a .mjs bundle. The runtime
    //   image ships its node_modules so `await import('node-rdkafka')` resolves at boot.
    // - `esbuild`: the janitor's compile-custom-tools calls esbuild's JS API at runtime, and that
    //   API refuses to run when inlined into a bundle ("The esbuild JavaScript API cannot be
    //   bundled"). Ships as a runtime dep of @posthog/agents-image (same pattern as node-rdkafka)
    //   so the bundle's `require('esbuild')` resolves from the image's node_modules.
    external: ['pg-native', 'node-rdkafka', 'esbuild'],
    loader: { '.json': 'json', '.sql': 'text' },
    define: { 'process.env.NODE_ENV': '"production"' },
    // CJS deps (pg, jose) call through to a global
    // `require`. ESM has no `require`; banner injects one. `typescript`
    // (bundled via the janitor's compile-custom-tools) also reaches for
    // `__filename` / `__dirname`, which ESM doesn't define — shim both from
    // `import.meta.url`. Same pattern as services/mcp/scripts/hono-esbuild-config.ts.
    banner: {
        js:
            `import { createRequire as __cr } from 'module';` +
            `import { fileURLToPath as __furl } from 'url';` +
            `import { dirname as __dn } from 'path';` +
            `const require = __cr(import.meta.url);` +
            `const __filename = __furl(import.meta.url);` +
            `const __dirname = __dn(__filename);`,
    },
    logLevel: 'info',
})

for (const name of Object.keys(ENTRY_POINTS)) {
    console.info(`built dist/${name}.mjs`)
}
