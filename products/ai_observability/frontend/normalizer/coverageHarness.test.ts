// Empirical coverage harness: runs the legacy normalizer and the recipe-based
// `RecipeNormalizer` over a sample of REAL production payloads and reports where
// they diverge. This is how the known divergences in `../utils.test.ts` were
// found, and how to re-validate after changing a recipe.
//
// It is gated on the sample files existing, so it SKIPS in CI and in a normal
// `jest` run — it only does work when you've pulled a fresh sample locally.
//
// ── Reproducing ────────────────────────────────────────────────────────────
// 1. Authenticate (opens SSO in your browser, once per region):
//      hogli metabase:login --region us
//      hogli metabase:login --region eu
// 2. Find the ClickHouse data-tier DB id for each region:
//      hogli metabase:databases --region us   # e.g. "PostHog ClickHouse PROD US ONLINE"
//      hogli metabase:databases --region eu   # e.g. "PostHog ClickHouse PROD EU Data Tier"
// 3. Sample uniformly by team (so high-volume teams don't dominate) into the
//    directory this harness reads (default /tmp/parser-coverage):
//      hogli metabase:query --region us --database-id <ID> --save /tmp/parser-coverage/sample-us.tsv <<'SQL'
//      SELECT team_id, toString(uuid) AS event_uuid, provider, model, input, output_choices
//      FROM ai_events
//      WHERE event = '$ai_generation'
//          AND timestamp > now() - INTERVAL 6 HOUR
//          AND cityHash64(toString(uuid)) % 500 = 0      -- ~0.2% prefilter, keeps the sort in memory
//          AND (input != '' OR output_choices != '')
//      LIMIT 3 BY team_id                                 -- uniform: at most 3 events per team
//      LIMIT 20000
//      SETTINGS max_execution_time = 120
//      SQL
//    (repeat with --region eu and --save .../sample-eu.tsv)
// 4. Run this harness:
//      RECIPE_COVERAGE_DIR=/tmp/parser-coverage pnpm --filter @posthog/frontend jest --testPathPattern=coverageHarness
//    It writes <dir>/report.md (bucketed divergences) and logs a one-line summary.
//
// NEVER commit the sample TSVs or the report — they contain raw customer payloads.

import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import type { CompatMessage } from '../types'
import * as legacy from '../utils'
import { RecipeNormalizer } from './index'

const DIR = process.env.RECIPE_COVERAGE_DIR ?? '/tmp/parser-coverage'
const REGIONS = ['us', 'eu'] as const
const samplePath = (region: string): string => join(DIR, `sample-${region}.tsv`)
const haveSamples = REGIONS.some((r) => existsSync(samplePath(r)))

interface Sample {
    region: string
    teamId: number
    eventUuid: string
    provider: string
    column: 'input' | 'output_choices'
    raw: string
}

function loadSamples(region: string): Sample[] {
    if (!existsSync(samplePath(region))) {
        return []
    }
    const lines = readFileSync(samplePath(region), 'utf8').split('\n').filter(Boolean)
    const header = lines[0].split('\t')
    const at = (cells: string[], name: string): string => cells[header.indexOf(name)]
    const out: Sample[] = []
    for (const line of lines.slice(1)) {
        const cells = line.split('\t')
        for (const column of ['input', 'output_choices'] as const) {
            const raw = at(cells, column)
            if (raw && raw !== '' && raw !== '\\N') {
                out.push({
                    region,
                    teamId: Number(at(cells, 'team_id')),
                    eventUuid: at(cells, 'event_uuid'),
                    provider: at(cells, 'provider'),
                    column,
                    raw,
                })
            }
        }
    }
    return out
}

// Order-insensitive deep equality, matching Jest's `toEqual`: object key order
// is not a behavioral difference, but array (message) order is. Treats a missing
// key and an explicit `undefined` as equal.
function deepEqual(a: unknown, b: unknown): boolean {
    if (a === b) {
        return true
    }
    if (a === null || b === null || typeof a !== 'object' || typeof b !== 'object') {
        return false
    }
    if (Array.isArray(a) || Array.isArray(b)) {
        return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((x, i) => deepEqual(x, b[i]))
    }
    const ao = a as Record<string, unknown>
    const bo = b as Record<string, unknown>
    const keys = (o: Record<string, unknown>): string[] => Object.keys(o).filter((k) => o[k] !== undefined)
    const ak = keys(ao)
    return ak.length === keys(bo).length && ak.every((k) => k in bo && deepEqual(ao[k], bo[k]))
}

// A coarse structural fingerprint so divergences with the same shape group together.
function signature(value: unknown, depth = 0): string {
    if (depth > 3) {
        return '…'
    }
    if (value === null) {
        return 'null'
    }
    if (Array.isArray(value)) {
        const uniq = [...new Set(value.slice(0, 5).map((v) => signature(v, depth + 1)))]
        return uniq.length === 1 ? `[${uniq[0]}*${value.length}]` : `[${uniq.join('|')}]`
    }
    if (typeof value === 'object') {
        const obj = value as Record<string, unknown>
        const tags = ['type', 'role']
            .filter((k) => k in obj)
            .map((k) => `${k}=${JSON.stringify(obj[k])}`)
            .join(',')
        const keys = Object.keys(obj).sort().join(',')
        return tags ? `{${keys}|${tags}}` : `{${keys}}`
    }
    return typeof value
}

const describeOrSkip = haveSamples ? describe : describe.skip

describeOrSkip('recipe coverage vs legacy (empirical)', () => {
    it('reports divergences over sampled production payloads', () => {
        const recipe = new RecipeNormalizer()
        const samples = REGIONS.flatMap(loadSamples)

        let match = 0
        const buckets = new Map<string, { count: number; example: Sample; legacy: string; recipe: string }>()

        for (const s of samples) {
            let parsed: unknown
            try {
                parsed = JSON.parse(s.raw)
            } catch {
                continue
            }
            const role = s.column === 'input' ? 'user' : 'assistant'
            const run = (fn: () => CompatMessage[]): CompatMessage[] | { error: string } => {
                try {
                    return fn()
                } catch (err) {
                    return { error: err instanceof Error ? err.message : String(err) }
                }
            }
            const a = run(() => legacy.normalizeMessages(parsed, role))
            const b = run(() => recipe.normalizeMessages(parsed, role))
            if (deepEqual(a, b)) {
                match++
                continue
            }
            const sig = signature(parsed)
            const existing = buckets.get(sig)
            if (existing) {
                existing.count++
            } else {
                buckets.set(sig, { count: 1, example: s, legacy: JSON.stringify(a), recipe: JSON.stringify(b) })
            }
        }

        const diverge = samples.length - match
        const lines = [
            `# Recipe coverage vs legacy`,
            '',
            `- samples: ${samples.length} across ${new Set(samples.map((s) => s.teamId)).size} teams`,
            `- match: ${match} (${((match / samples.length) * 100).toFixed(1)}%)`,
            `- diverge: ${diverge} (${((diverge / samples.length) * 100).toFixed(1)}%)`,
            '',
            '## Divergences by shape',
            '',
        ]
        for (const [sig, info] of [...buckets].sort((x, y) => y[1].count - x[1].count)) {
            lines.push(`### ${info.count}× \`${sig}\``)
            lines.push(
                `- example: team ${info.example.teamId} (${info.example.region}), \`${info.example.provider}\`, ${info.example.column}, uuid \`${info.example.eventUuid}\``
            )
            lines.push(`- legacy: \`${info.legacy.slice(0, 300).replace(/`/g, "'")}\``)
            lines.push(`- recipe: \`${info.recipe.slice(0, 300).replace(/`/g, "'")}\``)
            lines.push('')
        }
        writeFileSync(join(DIR, 'report.md'), lines.join('\n'))
        // eslint-disable-next-line no-console
        console.warn(
            `[coverage] ${samples.length} samples · ${match} match · ${diverge} diverge · report → ${join(DIR, 'report.md')}`
        )
    }, 120000)
})
