import { gzipObject, unGzipObject } from '../../src/cdp/utils'
import { insertHogFunction as _insertHogFunction } from './fixtures'

describe('Utils', () => {
    describe('gzip compressions', () => {
        it("should compress and decompress a string using gzip's sync functions", async () => {
            const input = { foo: 'bar' }
            const compressed = await gzipObject(input)
            expect(compressed).toMatchInlineSnapshot(`"H4sIAAAAAAAAE6tWSsvPV7JSSkosUqoFAO/1K/4NAAAA"`)
            const decompressed = await unGzipObject(compressed)
            expect(decompressed).toEqual(input)
        })
    })
})
