import { describe, expect, it } from 'vitest'

import { type NativeApprovalClass, type ToolRef, ToolRefSchema } from './spec'
import { resolveToolRefApprovalLevel } from './tool-approval'

/**
 * The tool-authorization chokepoint resolves every `ToolRef` kind, fail closed,
 * and the `assertNever` makes a new unhandled lane a compile error.
 */
const deps = {
    // Stand-in for agent-tools' `nativeToolApprovalClass`: identity-connect is an
    // intrinsic `approve` (links credentials); everything else here `allow`.
    nativeApprovalClass: (id: string): NativeApprovalClass =>
        id === '@posthog/identity-connect' ? 'approve' : 'allow',
}

const ref = (input: Record<string, unknown>): ToolRef => ToolRefSchema.parse(input)

describe('resolveToolRefApprovalLevel', () => {
    it('native: intrinsic approve ⇒ approve regardless of the ref flag', () => {
        expect(resolveToolRefApprovalLevel(ref({ kind: 'native', id: '@posthog/identity-connect' }), deps)).toBe(
            'approve'
        )
    })

    it('native: intrinsic read-only ⇒ allow', () => {
        expect(resolveToolRefApprovalLevel(ref({ kind: 'native', id: '@posthog/memory-read' }), deps)).toBe('allow')
    })

    it('native: author may escalate a read-only tool to approve, never the reverse', () => {
        expect(
            resolveToolRefApprovalLevel(
                ref({ kind: 'native', id: '@posthog/memory-read', requires_approval: true }),
                deps
            )
        ).toBe('approve')
    })

    it('custom: gate is the author ref flag', () => {
        expect(resolveToolRefApprovalLevel(ref({ kind: 'custom', id: 't', path: 't.ts' }), deps)).toBe('allow')
        expect(
            resolveToolRefApprovalLevel(ref({ kind: 'custom', id: 't', path: 't.ts', requires_approval: true }), deps)
        ).toBe('approve')
    })

    it('client: fails closed (no spec approval field today)', () => {
        expect(resolveToolRefApprovalLevel(ref({ kind: 'client', id: 'focus', description: 'd' }), deps)).toBe(
            'approve'
        )
    })
})
