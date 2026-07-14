import { patch } from '~/toolbar/patch'

describe('patch', () => {
    it('restores the original method on teardown', () => {
        const original = (): string => 'original'
        const source: { fn: () => string } = { fn: original }

        const unpatch = patch(source, 'fn', () => () => 'patched', 'key_a')
        expect(source.fn()).toBe('patched')

        unpatch()
        expect(source.fn).toBe(original)
    })

    it('tearing down a lower patch does not drop the patch stacked on top of it', () => {
        const calls: string[] = []
        const original = (): void => {
            calls.push('original')
        }
        const source: { fn: () => void } = { fn: original }

        const unpatchA = patch(
            source,
            'fn',
            (orig) => () => {
                ;(orig as () => void)()
                calls.push('A')
            },
            'key_a'
        )
        const unpatchB = patch(
            source,
            'fn',
            (orig) => () => {
                ;(orig as () => void)()
                calls.push('B')
            },
            'key_b'
        )

        // Tear down the first-installed (lower) patch while the second is still on top.
        unpatchA()

        // The top patch must keep working — a naive restore would have reverted straight to
        // `original` here and silently dropped B.
        calls.length = 0
        source.fn()
        expect(calls).toContain('B')

        unpatchB()
    })

    it('is idempotent for the same patch key', () => {
        const calls: string[] = []
        const original = (): void => {
            calls.push('original')
        }
        const source: { fn: () => void } = { fn: original }

        patch(
            source,
            'fn',
            (orig) => () => {
                ;(orig as () => void)()
                calls.push('once')
            },
            'key_a'
        )
        // Re-installing the same key must not stack a second wrapper that captures the first as
        // its "original" — that is what makes out-of-order teardown resurrect a stale wrapper.
        patch(
            source,
            'fn',
            (orig) => () => {
                ;(orig as () => void)()
                calls.push('twice')
            },
            'key_a'
        )

        source.fn()
        expect(calls).toEqual(['original', 'once'])
    })
})
