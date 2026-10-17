import { parseImageRef, parseV4UrlRef } from './content-ref'

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

describe('parseV4UrlRef', () => {
    const hash = 'a'.repeat(22)

    it('parses a day-scoped v4 URL ref that no v2 or v3 reader takes', () => {
        const ref = `imageurl:v4:7:2026-10-15:${hash}`
        expect(parseV4UrlRef(ref)).toEqual({ teamId: 7, keyDay: '2026-10-15', hash })
        expect(parseImageRef(ref)).toBeNull()
    })

    it.each([
        ['a month-scoped v3 ref', `imageurl:v3:7:2026-10:${hash}`],
        ['a content ref', `image:v4:7:2026-10-15:${hash}`],
        ['a day that does not exist', `imageurl:v4:7:2026-02-30:${hash}`],
        ['a team id of zero', `imageurl:v4:0:2026-10-15:${hash}`],
    ])('refuses %s', (_name, ref) => {
        expect(parseV4UrlRef(ref)).toBeNull()
    })
})
