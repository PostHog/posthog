import { describe, expect, it, vi } from 'vitest'

import { buildToolNameMap, providerSafeName } from './provider-safe-names'

describe('provider-safe-names', () => {
    describe('providerSafeName', () => {
        it('drops the leading underscore a leading `@` would introduce', () => {
            // The regression: the model echoes `posthog_meta-end-turn`, so the
            // safe form (and thus the reverse-map key) must match that — not
            // `_posthog_meta-end-turn`.
            expect(providerSafeName('@posthog/meta-end-turn')).toBe('posthog_meta-end-turn')
            expect(providerSafeName('@posthog/query')).toBe('posthog_query')
        })

        it('is idempotent on already-safe names (MCP `<prefix>__<name>`)', () => {
            expect(providerSafeName('linear__create-issue')).toBe('linear__create-issue')
        })

        it('preserves a legitimately leading underscore', () => {
            // `_` is already in the safe charset, so it was not introduced by
            // sanitization — leave it alone.
            expect(providerSafeName('_foo')).toBe('_foo')
        })

        it('never strips down to an empty name', () => {
            // Pathological all-unsafe id: keep the underscored fallback rather
            // than emit an empty (invalid) tool name.
            expect(providerSafeName('@/')).not.toBe('')
        })

        it('caps length at 128', () => {
            expect(providerSafeName('@' + 'a'.repeat(200)).length).toBe(128)
        })
    })

    describe('buildToolNameMap round-trip', () => {
        it('reverse-resolves the name the model actually emits', () => {
            const map = buildToolNameMap([
                '@posthog/meta-end-turn',
                '@posthog/meta-end-session',
                'linear__create-issue',
            ])
            // Pre-fix this key was `_posthog_meta-end-turn` and the lookup missed.
            expect(map.get('posthog_meta-end-turn')).toBe('@posthog/meta-end-turn')
            expect(map.get('posthog_meta-end-session')).toBe('@posthog/meta-end-session')
            expect(map.get('linear__create-issue')).toBe('linear__create-issue')
        })

        it('warns when two distinct ids collapse to the same safe name', () => {
            const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
            // `a.b` and `a_b` both sanitize to `a_b`; the second wins and the
            // first would be undispatchable, so the collision must be surfaced.
            const map = buildToolNameMap(['a.b', 'a_b'])
            expect(map.get('a_b')).toBe('a_b')
            expect(warn).toHaveBeenCalledOnce()
            warn.mockRestore()
        })
    })
})
