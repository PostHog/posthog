import { describe, expect, test } from 'bun:test'

import { loadMapContent, serializeMapBytes, serializeMapContent, SourcePair } from './js'

const SOURCE = 'const a = 1;\nconsole.log(a);\n//# sourceMappingURL=app.js.map\n'
const CHUNK_ID = '0192f0a0-1111-7000-8000-00000000abcd'
const RELEASE_ID = 'release-1'
const CHUNK_SIZE = 1024 * 1024

// The expected maps were recorded from the map rewriting that the parity goldens hold to posthog-cli.
const REWRITTEN: [name: string, map: string, injected: string, restored: string][] = [
    [
        'empty segments, unsorted columns and repeated tokens',
        '{"version":3,"sources":["a.ts","b.ts"],"names":["x","y"],"mappings":",,AAAA,,IACAA,AADA,AAAA;;;EAEEC,"}',
        '{"chunk_id":"0192f0a0-1111-7000-8000-00000000abcd","mappings":"8WAAA,IACAA,AADA","names":["x","y"],"sources":["a.ts","b.ts"],"version":3}',
        '{"mappings":"AAAA,IACAA,AADA","names":["x","y"],"sources":["a.ts","b.ts"],"version":3}',
    ],
    [
        'range mappings',
        '{"version":3,"sources":["a.ts"],"names":[],"mappings":"AAAA,CAAC,EAAE;AACA,GAAG","rangeMappings":"F;B"}',
        '{"chunk_id":"0192f0a0-1111-7000-8000-00000000abcd","mappings":"8WAAA,CAAC,EAAE;AACA,GAAG","names":[],"rangeMappings":"N;","sources":["a.ts"],"version":3}',
        '{"mappings":"AAAA,CAAC,EAAE;AACA,GAAG","names":[],"rangeMappings":"F;","sources":["a.ts"],"version":3}',
    ],
    [
        'a source root, an ignore list, both debug IDs and fields the encoder drops',
        '{"version":3,"file":"app.js","sourceRoot":"src/","sources":["a.ts","/abs.ts"],"sourcesContent":["a",null],"names":["n",7],"mappings":"AAAAA,KCAAC","ignoreList":[1],"debugId":"0192F0A0-2222-7000-8000-00000000ABCD","debug_id":"0192f0a0-3333-7000-8000-00000000abcd","x_google_ignoreList":[0],"custom":{"b":1,"a":[true,null]}}',
        '{"chunk_id":"0192f0a0-1111-7000-8000-00000000abcd","debugId":"0192F0A0-2222-7000-8000-00000000ABCD","custom":{"a":[true,null],"b":1},"debug_id":"0192f0a0-3333-7000-8000-00000000abcd","file":"app.js","ignoreList":[1],"mappings":"8WAAAA,KCAAC","names":["n","7"],"sourceRoot":"src/","sources":["a.ts","/abs.ts"],"sourcesContent":["a",null],"version":3,"x_google_ignoreList":[0]}',
        '{"debugId":"0192F0A0-2222-7000-8000-00000000ABCD","custom":{"a":[true,null],"b":1},"debug_id":"0192f0a0-3333-7000-8000-00000000abcd","file":"app.js","ignoreList":[1],"mappings":"AAAAA,KCAAC","names":["n","7"],"sourceRoot":"src/","sources":["a.ts","/abs.ts"],"sourcesContent":["a",null],"version":3,"x_google_ignoreList":[0]}',
    ],
    [
        'a camelCase debug ID only',
        '{"version":3,"sources":["a.ts"],"names":[],"mappings":"AAAA","debugId":"0192F0A0-2222-7000-8000-00000000ABCD"}',
        '{"chunk_id":"0192f0a0-1111-7000-8000-00000000abcd","debugId":"0192F0A0-2222-7000-8000-00000000ABCD","debug_id":"0192f0a0-2222-7000-8000-00000000abcd","mappings":"8WAAA","names":[],"sources":["a.ts"],"version":3}',
        '{"debugId":"0192F0A0-2222-7000-8000-00000000ABCD","debug_id":"0192f0a0-2222-7000-8000-00000000abcd","mappings":"AAAA","names":[],"sources":["a.ts"],"version":3}',
    ],
    [
        'a range bit after an empty segment',
        '{"version":3,"sources":["a.ts"],"names":[],"mappings":"AAAA,,CAAC,EAAE","rangeMappings":"E"}',
        '{"chunk_id":"0192f0a0-1111-7000-8000-00000000abcd","mappings":"8WAAA,CAAC,EAAE","names":[],"rangeMappings":"C","sources":["a.ts"],"version":3}',
        '{"mappings":"AAAA,CAAC,EAAE","names":[],"rangeMappings":"C","sources":["a.ts"],"version":3}',
    ],
    [
        'unsorted tokens at the same position',
        '{"version":3,"sources":["a.ts"],"names":[],"mappings":"IAAA,AACA,JAEA,AAEA"}',
        '{"chunk_id":"0192f0a0-1111-7000-8000-00000000abcd","mappings":"8WAKA,IALA,AACA","names":[],"sources":["a.ts"],"version":3}',
        '{"mappings":"AAKA,IALA,AACA","names":[],"sources":["a.ts"],"version":3}',
    ],
]

const section = (line: number, column: number, source: string, mappings: string): string =>
    `{"offset":{"line":${line},"column":${column}},"map":{"version":3,"sources":["${source}","shared.ts"],"sourcesContent":["${source} text",null],"names":["${source}Name","shared"],"mappings":"${mappings}","ignoreList":[1]}}`
const SECTIONS = [
    section(0, 0, 'a.ts', 'AAAAA,ECAAC'),
    section(0, 20, 'b.ts', 'AAAAA;ACAAC'),
    section(1, 5, 'c.ts', 'AAAA'),
]
const indexed = (sections: string[]): string => `{"version":3,"file":"app.js","sections":[${sections.join(',')}]}`
const FLATTENED =
    '{"chunk_id":"0192f0a0-1111-7000-8000-00000000abcd","file":"app.js","ignoreList":[1],"mappings":"8WAAAA,ECAAC,kBCAAC;ADAAD,KEAA","names":["a.tsName","shared","b.tsName","c.tsName"],"sources":["a.ts","shared.ts","b.ts","c.ts"],"sourcesContent":["a.ts text",null,"b.ts text","c.ts text"],"version":3}'

const pairOf = (map: string): SourcePair => new SourcePair('/app.js', SOURCE, '/app.js.map', loadMapContent(map))

function inject(map: string): SourcePair {
    const pair = pairOf(map)
    pair.addChunkId(CHUNK_ID, RELEASE_ID)
    return pair
}

describe('SourcePair', () => {
    test.each(REWRITTEN)('rewrites a map with %s', (_name, map, injected, restored) => {
        const pair = inject(map)

        expect(serializeMapContent(pair.map)).toBe(injected)

        pair.removeChunkId(CHUNK_ID)

        expect(serializeMapContent(pair.map)).toBe(restored)
    })

    test.each([
        ['in offset order', SECTIONS],
        ['in reverse order', [...SECTIONS].reverse()],
    ])('flattens sections listed %s', (_name, sections) => {
        expect(serializeMapContent(inject(indexed(sections)).map)).toBe(FLATTENED)
    })

    test('reports an invalid section before a section without a map', () => {
        const withoutMap = '{"offset":{"line":0,"column":0}}'
        const invalid = '{"offset":{"line":1,"column":0},"map":{"version":"three","mappings":""}}'

        expect(() => inject(indexed([withoutMap, invalid]))).toThrow('invalid type for version: expected u32')
    })

    test.each([...REWRITTEN.map(([name, map]) => [name, map]), ['sections', indexed(SECTIONS)]])(
        'rewrites a map with %s the same with and without the serialization round trip',
        (_name, map) => {
            const direct = pairOf(map!)
            const roundTrip = pairOf(map!)
            roundTrip.map.hasFloats = undefined

            direct.addChunkId(CHUNK_ID, RELEASE_ID)
            roundTrip.addChunkId(CHUNK_ID, RELEASE_ID)

            expect(serializeMapContent(direct.map)).toBe(serializeMapContent(roundTrip.map))
        }
    )

    test.each([
        ['{"names":[1.5]}', true],
        ['{"x":{"deep":[1e2]}}', true],
        ['{"x":-0}', true],
        ['{"x":18446744073709551616}', true],
        ['{"x":[1,-1,"1.5"],"version":3}', false],
    ])('knows whether %s has a float', (map, hasFloats) => {
        expect(loadMapContent(map).hasFloats).toBe(hasFloats)
    })

    test.each([
        ['no fields', '{}'],
        ['IDs only', '{"chunk_id":"c","release_id":"r","debugId":"d"}'],
        ['fields only', '{"version":3,"mappings":""}'],
        ['text longer than one chunk of bytes', `{"chunk_id":"c","sourcesContent":["${'é😀x'.repeat(CHUNK_SIZE)}"]}`],
    ])('writes a map with %s as the same bytes as its text', (_name, text) => {
        const map = loadMapContent(text)

        expect(Buffer.concat(serializeMapBytes(map)).toString('utf8')).toBe(serializeMapContent(map))
    })
})
