import { mkdtempSync, readFileSync, readdirSync, rmSync } from 'fs'
import os from 'os'
import path from 'path'

import { writeJson } from './evidence-file'

describe('writeJson', () => {
    let dir: string

    beforeEach(() => {
        dir = mkdtempSync(path.join(os.tmpdir(), 'evidence-file-'))
    })

    afterEach(() => {
        rmSync(dir, { recursive: true, force: true })
    })

    it.each<[string, unknown]>([
        ['an empty array', []],
        [
            'an array of nested entries',
            [
                { unitId: 'u-1', kind: 'event', at: 1, tags: ['a', 'b'], nested: { empty: {}, none: [] } },
                { unitId: 'u-2', error: 'line one\nline two', status: null },
            ],
        ],
        ['an array whose undefined and function elements JSON writes as null', [undefined, 1, () => 2, 'three']],
        ['an array with empty slots first and between entries', Object.assign([], { 1: 'b', 3: 'd' })],
        ['an array of arrays', [[], [[1], { a: [2] }]]],
        ['an object', { steps: [{ index: 0 }], verdict: 'sustained' }],
    ])('writes %s in the bytes JSON.stringify gives', (_, value) => {
        writeJson(dir, 'out.json', value)

        expect(readFileSync(path.join(dir, 'out.json'), 'utf8')).toBe(JSON.stringify(value, null, 2))
        expect(readdirSync(dir)).toEqual(['out.json'])
    })
})
