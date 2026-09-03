import { z } from 'zod'

import { FEATURE_FLAGS } from 'lib/constants'

/**
 * Turn zod's JIT parser compiler off for a share of users so we can measure what it costs us.
 *
 * zod compiles a parser per schema with `new Function`, which needs `'unsafe-eval'` in `script-src`
 * — about half of all CSP violations the app reports. The compiler pays for itself only when one
 * schema is parsed many times, and most of ours are parsed a handful of times per page load, so
 * turning it off may well be free or better. Measure rather than assume.
 *
 * The flag is read from the bootstrap Django renders into the page, not from `featureFlagLogic`.
 * zod compiles a schema the first time it is parsed and caches the result, so a flag arriving later
 * would leave a mix of compiled and interpreted schemas and a measurement that means nothing.
 */
export function configureZod(): void {
    const bootstrapFlags = window.POSTHOG_USER_IDENTITY_WITH_FLAGS?.featureFlags
    z.config({ jitless: !!bootstrapFlags?.[FEATURE_FLAGS.ZOD_JITLESS] })
}
