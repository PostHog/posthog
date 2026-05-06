/**
 * Fails CI if a slug declared in `features.ts` isn't tagged anywhere in the frontend.
 *
 * Run with: `pnpm exec tsx playwright/docs-capture/lint-slugs.ts` (or via `node --import tsx`).
 *
 * The check is intentionally a simple text grep on both ends: it parses slugs out of
 * `features.ts` (rather than importing it, which would drag in frontend path aliases) and
 * verifies that *some* element carries `data-feature="<slug>"`. The runner's actual
 * `expect(...).toBeVisible()` call is what catches the harder case where the tag exists in
 * source but is never rendered.
 */
import { execSync } from 'child_process'
import { readFileSync } from 'fs'
import { join } from 'path'

const REPO_ROOT = join(__dirname, '..', '..')
const FEATURES_FILE = join(__dirname, 'features.ts')
const SEARCH_PATHS = ['frontend/src', 'products']

function parseSlugs(): string[] {
    const source = readFileSync(FEATURES_FILE, 'utf8')
    const matches = source.matchAll(/^\s*slug:\s*'([a-z0-9][a-z0-9-]*)',?\s*$/gm)
    return [...new Set([...matches].map((m) => m[1]))]
}

function isSlugTagged(slug: string): boolean {
    try {
        execSync(`grep -rq 'data-feature="${slug}"' ${SEARCH_PATHS.join(' ')}`, {
            cwd: REPO_ROOT,
            stdio: 'ignore',
        })
        return true
    } catch {
        return false
    }
}

const slugs = parseSlugs()

if (slugs.length === 0) {
    // eslint-disable-next-line no-console
    console.error(`docs-capture: no slugs found in ${FEATURES_FILE} — did the registry shape change?`)
    process.exit(1)
}

const missing = slugs.filter((slug) => !isSlugTagged(slug))

if (missing.length > 0) {
    // eslint-disable-next-line no-console
    console.error(
        `docs-capture: the following slugs are declared in features.ts but no element carries\n` +
            `data-feature="<slug>" anywhere under ${SEARCH_PATHS.join(' or ')}:\n` +
            missing.map((s) => `  - ${s}`).join('\n') +
            `\n\nEither tag the relevant element, or remove the entry from features.ts.`
    )
    process.exit(1)
}

// eslint-disable-next-line no-console
console.log(`docs-capture: all ${slugs.length} slug(s) resolve.`)
