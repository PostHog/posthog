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
 * zod binds `jitless` when it constructs each object schema, so this must run before any module
 * that builds a schema at module scope evaluates. src/index.tsx imports and calls it before it
 * imports the App chunk.
 */
export function configureZod(): void {
    z.config({ jitless: true })
}
