import vector from '~/ingestion/pipelines/sessionreplay/ai-research/v4-keys/encryption-vector-v4.json'
import { parseImageRef } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/content-ref'

import { parseV4UrlRef, publicFontRefOf } from './v4-url-ref'

describe('parseV4UrlRef', () => {
    const hash = 'a'.repeat(22)

    it.each([
        ['imageurl', 'image'],
        ['fonturl', 'font'],
    ])('parses a month-scoped v4 %s ref that no v2 or v3 reader takes', (prefix, asset) => {
        const ref = `${prefix}:v4:7:2026-10:${hash}`
        expect(parseV4UrlRef(ref)).toEqual({ scope: 'team', asset, teamId: 7, keyMonth: '2026-10', hash })
        expect(parseImageRef(ref)).toBeNull()
    })

    it('names a public font file by the same reference as the recorder, and no other URL', () => {
        const ref = publicFontRefOf(vector.publicFontUrl.url)
        expect(ref).toBe(vector.publicFontUrl.ref)
        expect(parseV4UrlRef(ref!)).toEqual({ scope: 'public', asset: 'font', hash: ref!.split(':').pop() })
        expect(parseImageRef(ref!)).toBeNull()
        expect(vector.publicFontUrl.teamUrls.map(publicFontRefOf)).toEqual(
            vector.publicFontUrl.teamUrls.map(() => undefined)
        )
    })

    it.each([
        ['a v3 ref', `imageurl:v3:7:2026-10:${hash}`],
        ['a content ref', `image:v4:7:2026-10:${hash}`],
        ['a month that does not exist', `imageurl:v4:7:2026-13:${hash}`],
        ['a day-scoped ref', `imageurl:v4:7:2026-10-15:${hash}`],
        ['a team id of zero', `imageurl:v4:0:2026-10:${hash}`],
        ['a bundled font marker, which names no URL', 'fonturl:v4:bundled:open-sans'],
        ['a public image ref, which the recorder never writes', `imageurl:v4:public:${hash}`],
    ])('refuses %s', (_name, ref) => {
        expect(parseV4UrlRef(ref)).toBeNull()
    })
})
