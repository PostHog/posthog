// Turn zod's JIT parser compiler off in browser bundles.
//
// zod compiles a parser per schema with `new Function`, which needs `'unsafe-eval'` in `script-src`.
// That was about half of every CSP violation the app reported, and `script-src` cannot be enforced
// while we need it. A 48-hour measurement at 50% of traffic found jitless performance-neutral: INP
// p75 was identical at the three largest samples, LCP was equal or better, and eval violations fell
// from 33 to 14-20 per 1000 pageviews.
//
// zod reads `jitless` when it constructs each object schema. The bundler sets it in zod's own config
// object, so it is on before any schema exists, in every chunk and every entry point. A `z.config()`
// call in app code cannot promise that: a shared chunk can build a schema before the entry body that
// makes the call runs, and an entry that calls it eagerly loads zod on pages that use no schema.
export const ZOD_CORE_FILE = /[\\/]zod[\\/]v4[\\/]core[\\/]core\.js$/

const DEFAULT_CONFIG = 'export const globalConfig = {};'

export function withJitlessZod(source, filePath) {
    const contents = source.replace(DEFAULT_CONFIG, 'export const globalConfig = { jitless: true };')
    if (contents === source) {
        // zod changed its config declaration upstream. Fail the build rather than ship the JIT compiler.
        throw new Error(`zod-jitless: no '${DEFAULT_CONFIG}' found in ${filePath}`)
    }
    return contents
}
