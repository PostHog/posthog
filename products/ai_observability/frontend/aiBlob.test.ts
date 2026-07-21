import { parseAiBlobPointer, resolveAiBlobUrl, resolveDataUri } from './aiBlob'

const HASH = 'a'.repeat(64)
const POINTER = `phaiblob://v1/sha256/${HASH}?mime=image%2Fpng&size=131072`

describe('aiBlob', () => {
    it('parses a pointer', () => {
        expect(parseAiBlobPointer(POINTER)).toEqual({
            version: 'v1',
            algo: 'sha256',
            hash: HASH,
            mime: 'image/png',
            size: 131072,
        })
    })

    it('resolves a pointer to the environment endpoint', () => {
        expect(resolveAiBlobUrl(POINTER, 1)).toBe(`/api/projects/1/ai_blob/v1/sha256/${HASH}`)
    })

    it.each([
        ['http url', 'https://example.com/a.png'],
        ['data uri', 'data:image/png;base64,AAAA'],
        ['plain text', 'hello'],
        ['bad hash', 'phaiblob://v1/sha256/xyz?mime=a&size=1'],
        ['unknown algo', `phaiblob://v1/md5/${HASH}?mime=a&size=1`],
        ['old scheme', `phblob://v1/sha256/${HASH}?mime=a&size=1`],
    ])('passes through unchanged: %s', (_name, value) => {
        expect(parseAiBlobPointer(value)).toBeNull()
        expect(resolveAiBlobUrl(value, 1)).toBe(value)
    })

    it('passes through when teamId is missing', () => {
        expect(resolveAiBlobUrl(POINTER, null)).toBe(POINTER)
    })

    it('resolves a pointer data field to the blob endpoint, ignoring the passed mime type', () => {
        expect(resolveDataUri(POINTER, 'image/png', 1)).toBe(`/api/projects/1/ai_blob/v1/sha256/${HASH}`)
    })

    it('builds a data: URI from raw base64 when the data field is not a pointer', () => {
        expect(resolveDataUri('AAAA', 'image/png', 1)).toBe('data:image/png;base64,AAAA')
    })
})
