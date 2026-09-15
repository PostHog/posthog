import { z } from 'zod'

/**
 * Turn zod's JIT parser compiler off.
 *
 * zod compiles a parser per schema with `new Function`, which needs `'unsafe-eval'` in `script-src`.
 * That was about half of every CSP violation the app reported, and `script-src` cannot be enforced
 * while we need it. A 48-hour measurement at 50% of traffic found jitless performance-neutral: INP
 * p75 was identical at the three largest samples, LCP was equal or better, and eval violations fell
 * from 33 to 14-20 per 1000 pageviews.
 *
 * zod binds `jitless` when it constructs each object schema, so this module must evaluate before any
 * module that builds a schema at module scope. Each esbuild entry point bundles its own copy of zod
 * with its own config, so every browser entry point imports this module itself:
 * - src/index.tsx imports it on its own before it imports the App chunk.
 * - src/exporter/index.tsx and src/render-query/index.tsx import it for its side effect ahead of their
 *   other imports. ESM evaluates imports in declaration order, so it runs before the modules that build
 *   schemas.
 */
z.config({ jitless: true })
