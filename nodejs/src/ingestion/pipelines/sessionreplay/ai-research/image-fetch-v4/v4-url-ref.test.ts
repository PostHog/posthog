import { parseImageRef } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/content-ref'

import { parseV4UrlRef } from './v4-url-ref'

describe('parseV4UrlRef', () => {
    const hash = 'a'.repeat(22)

    it('parses a month-scoped v4 URL ref that no v2 or v3 reader takes', () => {
        const ref = `imageurl:v4:7:2026-10:${hash}`
        expect(parseV4UrlRef(ref)).toEqual({ teamId: 7, keyMonth: '2026-10', hash })
        expect(parseImageRef(ref)).toBeNull()
    })

    it.each([
        ['a v3 ref', `imageurl:v3:7:2026-10:${hash}`],
        ['a content ref', `image:v4:7:2026-10:${hash}`],
        ['a month that does not exist', `imageurl:v4:7:2026-13:${hash}`],
        ['a day-scoped ref', `imageurl:v4:7:2026-10-15:${hash}`],
        ['a team id of zero', `imageurl:v4:0:2026-10:${hash}`],
    ])('refuses %s', (_name, ref) => {
        expect(parseV4UrlRef(ref)).toBeNull()
    })
})
