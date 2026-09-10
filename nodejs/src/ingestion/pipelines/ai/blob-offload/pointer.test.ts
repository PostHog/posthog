import { encodeBlobPointer, isBlobPointer, parseBlobPointer } from './pointer'

const HASH = 'a'.repeat(64)

describe('blob pointer', () => {
    it('round-trips encode -> parse', () => {
        const uri = encodeBlobPointer({ algo: 'sha256', hash: HASH, mime: 'image/png', size: 123456 })
        expect(uri).toBe(`phaiblob://v1/sha256/${HASH}?mime=image%2Fpng&size=123456`)
        expect(parseBlobPointer(uri)).toEqual({ algo: 'sha256', hash: HASH, mime: 'image/png', size: 123456 })
    })

    it('detects pointers by scheme', () => {
        expect(isBlobPointer(`phaiblob://v1/sha256/${HASH}?mime=image%2Fpng&size=1`)).toBe(true)
        expect(isBlobPointer('data:image/png;base64,AAAA')).toBe(false)
    })

    it.each([
        ['not a pointer', 'https://example.com/img.png'],
        ['unknown version', `phaiblob://v9/sha256/${HASH}?mime=image%2Fpng&size=1`],
        ['unknown algo', `phaiblob://v1/md5/${HASH}?mime=image%2Fpng&size=1`],
        ['bad hash length', 'phaiblob://v1/sha256/abc123?mime=image%2Fpng&size=1'],
        ['non-hex hash', `phaiblob://v1/sha256/${'z'.repeat(64)}?mime=image%2Fpng&size=1`],
        ['missing mime', `phaiblob://v1/sha256/${HASH}?size=1`],
        ['missing size', `phaiblob://v1/sha256/${HASH}?mime=image%2Fpng`],
        ['non-integer size', `phaiblob://v1/sha256/${HASH}?mime=image%2Fpng&size=1.5`],
        ['unparseable', 'phaiblob://'],
    ])('parse returns null for %s', (_name, value) => {
        expect(parseBlobPointer(value)).toBeNull()
    })
})
