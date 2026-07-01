import { describe, expect, it } from 'vitest'

import { ALL_TOOLS } from './registry'
import { FAIL_CLOSED_NATIVE_APPROVAL, nativeToolApprovalClass } from './tool-authorization'

/**
 * Accessor behavior only — totality (every tool declares `approval`) is a
 * compile error via the required field. Verifies the accessor reads that field
 * and fails closed on an id no tool owns.
 */
describe('native tool authorization accessor', () => {
    it('returns each registered tool’s own declared class (accessor can’t drift from the field)', () => {
        // Floor: an emptied registry would make the drift filter assert nothing and
        // pass vacuously — fail loud instead.
        expect(ALL_TOOLS.length).toBeGreaterThanOrEqual(40)
        const drift = ALL_TOOLS.filter((t) => nativeToolApprovalClass(t.id) !== t.schema.approval).map((t) => t.id)
        expect(drift, `accessor disagrees with the tool’s declared approval: ${drift.join(', ')}`).toEqual([])
    })

    it('fails closed on an unregistered id', () => {
        expect(nativeToolApprovalClass('@posthog/not-a-real-tool')).toBe(FAIL_CLOSED_NATIVE_APPROVAL)
        expect(FAIL_CLOSED_NATIVE_APPROVAL).toBe('approve')
    })
})
