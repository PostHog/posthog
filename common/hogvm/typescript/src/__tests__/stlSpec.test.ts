import * as fs from 'fs'
import * as path from 'path'

import { ASYNC_STL, STL } from '../stl/stl'

const SPEC_PATH = path.join(__dirname, '..', '..', '..', 'spec', 'stl.json')
const ALL_VMS = ['python', 'typescript', 'rust']

describe('STL spec manifest', () => {
    // Importing the STL already fails when a TypeScript builtin is missing from the spec; this
    // covers the other direction — a spec function marked as implemented here but absent.
    test('every spec function marked typescript is implemented', () => {
        const spec: Record<string, { implementations?: string[] }> = JSON.parse(
            fs.readFileSync(SPEC_PATH, 'utf-8')
        ).functions
        const implemented = { ...STL, ...ASYNC_STL }
        const missing = Object.keys(spec)
            .filter((name) => (spec[name].implementations ?? ALL_VMS).includes('typescript'))
            .filter((name) => !(name in implemented))
            .sort()
        expect(missing).toEqual([])
    })
})
