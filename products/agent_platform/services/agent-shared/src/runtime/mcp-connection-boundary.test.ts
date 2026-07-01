import { readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

/**
 * The owner-scoped `resolve` is the IDOR boundary only if it's the sole reader of
 * `sensitive_configuration`. This fails the build if any non-test file other than
 * the connection store references that column.
 */
const SRC_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const ALLOWED = ['runtime/mcp-connection-store.ts']

function nonTestSourcesReferencing(token: string): string[] {
    const out: string[] = []
    const walk = (dir: string): void => {
        for (const name of readdirSync(dir)) {
            const p = join(dir, name)
            if (statSync(p).isDirectory()) {
                walk(p)
                continue
            }
            if (!p.endsWith('.ts') || p.endsWith('.test.ts')) {
                continue
            }
            if (readFileSync(p, 'utf-8').includes(token)) {
                out.push(relative(SRC_ROOT, p))
            }
        }
    }
    walk(SRC_ROOT)
    return out.sort()
}

describe('connection-bearer chokepoint (no second reader)', () => {
    it('reads of sensitive_configuration are confined to the owner-scoped store', () => {
        expect(nonTestSourcesReferencing('sensitive_configuration')).toEqual(ALLOWED)
    })
})
