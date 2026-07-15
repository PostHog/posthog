import { readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

/**
 * Approval-wire chokepoint oracle: fails the build if any non-test janitor
 * source touches `approver_scope` directly instead of going through the shared
 * `serializeApprovalRequest` (which resolves the type). See Persistence.spec.md
 * "approval-wire-resolved".
 */
const SRC_ROOT = dirname(fileURLToPath(import.meta.url))
const ALLOWED: string[] = []

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

describe('approval wire chokepoint (single serializer)', () => {
    it('approval routes never bypass the shared serializer', () => {
        expect(nonTestSourcesReferencing('approver_scope')).toEqual(ALLOWED)
    })
})
