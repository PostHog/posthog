import { describe, expect, test } from 'bun:test'

import { decodeUtf8 } from '../json'
import { hermesMapBytes, readHermesMap, splitHermesMap, type HermesMap } from './hermes'
import { isEmptyMapContent, loadMapContent, serializeMapContent } from './js'

const LARGE_ARRAY_BYTES = 300 * 1024
const MAX_DEPTH = 127
const LEVELS_ABOVE_ELEMENT = 2

const fill = (element: string, bytes = LARGE_ARRAY_BYTES): string =>
    Array.from({ length: Math.ceil(bytes / Buffer.byteLength(element)) }, () => element).join(',')
const nested = (depth: number): string => `${'['.repeat(depth)}${']'.repeat(depth)}`

const TRICKY_ELEMENTS = [
    '"a \\"]quoted\\" [bracket, {brace}"',
    '"ends with a backslash \\\\"',
    '"escaped \\u00e9 and \\ud83d\\ude00, raw é and 😀 and 日本"',
    'null',
    ' [1, 1.0, 1e3, -0, {"b":"]","a":[]}] ',
    '\n{"z": "}", "a": {"nested": ["\\"", "\\\\"]}}\t',
].join(',')

const VALID: [name: string, text: string][] = [
    ['an empty object', ' { } '],
    ['ids only', '{"chunk_id":"c","release_id":null,"debugId":"d"}'],
    [
        'a small composed map with whitespace',
        ' {\n "version" : 3, "chunkId": "c", "sources": ["a.js"], "mappings": "AAAA",\r\n "x_hermes_function_offsets": {"0": [1, 2]} } \n',
    ],
    [
        'a large array of tricky elements',
        `{"sourcesContent":[${fill(TRICKY_ELEMENTS, 3 * 1024 * 1024)}],"mappings":""}`,
    ],
    ['a large array with whitespace around it', `{"names" : [ ${fill('"n" ')} ] , "version":3}`],
    [
        'large sections that are all empty',
        `{"sections":[${fill('{"offset":{"line":0,"column":0},"map":{"mappings":""}}')}]}`,
    ],
    [
        'large sections whose first map is not empty',
        `{"sections":[{"map":{"mappings":"AAAA"}},${fill('{"map":{"mappings":""}}')}]}`,
    ],
    ['a repeated key whose last value is small', `{"sources":[${fill('"a.js"')}],"sources":[]}`],
    ['a repeated key whose last value is large', `{"sources":[],"sources":[${fill('"a.js"')}]}`],
    ['keys that sort differently as UTF-8 and UTF-16', '{"￿":1,"😀":2,"é":3,"Z":4,"z":5}'],
    [
        'an element at the recursion limit',
        `{"sources":[${fill('"a.js"')},${nested(MAX_DEPTH - LEVELS_ABOVE_ELEMENT)}]}`,
    ],
]

const INVALID: [name: string, bytes: Buffer][] = [
    [
        'an element past the recursion limit',
        Buffer.from(`{"sources":[${fill('"a.js"')},${nested(MAX_DEPTH - LEVELS_ABOVE_ELEMENT + 1)}]}`),
    ],
    ['a trailing comma in a large array', Buffer.from(`{"sources":[${fill('"a.js"')},]}`)],
    ['a large array that never closes', Buffer.from(`{"sources":[${fill('"a.js"')}`)],
    ['a repeated chunk ID', Buffer.from('{"chunk_id":"a","chunkId":"b"}')],
    ['a chunk ID that is a large array', Buffer.from(`{"chunk_id":[${fill('"a"')}]}`)],
    ['text after the map', Buffer.from('{"version":3} x')],
    ['a byte order mark', Buffer.from('﻿{"version":3}')],
    [
        'invalid UTF-8 in a large array',
        Buffer.concat([Buffer.from(`{"sources":[${fill('"a.js"')},"`), Buffer.from([0xff]), Buffer.from('"]}')]),
    ],
]

const summary = (map: HermesMap): object => ({
    releaseId: map.releaseId,
    chunkId: map.chunkId,
    debugId: map.debugId,
    composed: map.composed,
    empty: map.empty,
})

function wholeTextSummary(text: string): { summary: object; serialized: string } {
    const map = loadMapContent(text)
    return {
        summary: {
            releaseId: map.releaseId,
            chunkId: map.chunkId,
            debugId: map.debugId,
            composed: map.fields.has('x_hermes_function_offsets'),
            empty: isEmptyMapContent(map),
        },
        serialized: serializeMapContent(map),
    }
}

function failure(action: () => unknown): string {
    try {
        action()
    } catch (error) {
        return String(error)
    }
    return 'no failure'
}

describe('readHermesMap', () => {
    test.each(VALID)('reads %s in pieces as it reads the whole text', (_name, text) => {
        const expected = wholeTextSummary(text)

        const all = splitHermesMap(Buffer.from(text), 'all')
        const ids = splitHermesMap(Buffer.from(text), 'ids')

        expect(summary(all)).toEqual(expected.summary)
        expect(hermesMapBytes(all, all.body).toString('utf8')).toBe(expected.serialized)
        expect(summary(ids)).toEqual(expected.summary)
        expect(ids.body).toEqual([])
    })

    test.each(INVALID)('fails on %s as the whole-text reader does', (_name, bytes) => {
        const expected = failure(() => loadMapContent(decodeUtf8(bytes)))

        expect(expected).not.toBe('no failure')
        expect(failure(() => readHermesMap(bytes, 'all'))).toBe(expected)
        expect(failure(() => readHermesMap(bytes, 'ids'))).toBe(expected)
    })
})
