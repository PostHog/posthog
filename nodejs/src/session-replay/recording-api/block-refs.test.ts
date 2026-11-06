import sodium from 'libsodium-wrappers'

import { BlockLocation, blockRefEncoder, decodeBlockRef } from './block-refs'

describe('block refs', () => {
    const sessionKey = new Uint8Array(32).fill(1)
    const location: BlockLocation = {
        teamId: 1,
        sessionId: 'session-123',
        key: 'session_recordings/30d/1764634738680-3cca0f5d3c7cc7ee',
        startByte: 100,
        endByte: 250,
    }

    beforeAll(async () => {
        await sodium.ready
    })

    it('names a block the same way every time, so its URL stays cacheable', () => {
        const ref = blockRefEncoder(sessionKey)(location)

        expect(blockRefEncoder(sessionKey)(location)).toBe(ref)
        expect(ref).not.toContain('session_recordings')
        expect(decodeBlockRef(sessionKey, ref, 1, 'session-123')).toEqual({
            key: location.key,
            startByte: 100,
            endByte: 250,
        })
    })

    it.each([
        ['another session key', (ref: string) => decodeBlockRef(new Uint8Array(32).fill(2), ref, 1, 'session-123')],
        ['another session', (ref: string) => decodeBlockRef(sessionKey, ref, 1, 'session-999')],
        ['another team', (ref: string) => decodeBlockRef(sessionKey, ref, 2, 'session-123')],
        [
            'a tampered ref',
            (ref: string) =>
                decodeBlockRef(sessionKey, ref.slice(0, -2) + (ref.endsWith('AA') ? 'BB' : 'AA'), 1, 'session-123'),
        ],
        [
            'an unknown version',
            (ref: string) => decodeBlockRef(sessionKey, ref.replace(/^v1\./, 'v2.'), 1, 'session-123'),
        ],
        ['an empty body', () => decodeBlockRef(sessionKey, 'v1.', 1, 'session-123')],
        ['a body shorter than its nonce', () => decodeBlockRef(sessionKey, 'v1.AAAA', 1, 'session-123')],
        ['an extra segment', (ref: string) => decodeBlockRef(sessionKey, `${ref}.x`, 1, 'session-123')],
    ])('rejects a ref read with %s', (_, decode) => {
        expect(decode(blockRefEncoder(sessionKey)(location))).toBeNull()
    })
})
