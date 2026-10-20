import { parseImageRef } from './content-ref'

describe('parseImageRef', () => {
    const hash = 'a'.repeat(22)

    it.each([
        ['image', 2, 'bytes'],
        ['imageurl', 2, 'url'],
        ['image', 3, 'bytes'],
        ['imageurl', 3, 'url'],
    ] as const)('parses a scoped %s ref of dataset v%s', (prefix, version, source) => {
        expect(parseImageRef(`${prefix}:v${version}:42:2026-09:${hash}`)).toEqual({
            teamId: '42',
            sessionMonth: '2026-09',
            hash,
            source,
            version,
        })
    })

    it('rejects a scoped ref of a dataset version it does not know', () => {
        expect(parseImageRef(`image:v4:42:2026-09:${hash}`)).toBeNull()
        expect(parseImageRef(`image:v1:42:2026-09:${hash}`)).toBeNull()
    })
})
