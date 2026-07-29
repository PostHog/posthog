import fs from 'fs'
import path from 'path'

import { parseJSON } from '~/common/utils/json-parse'

const BalancedSequencer = require('../test-sequencer.js')

type FakeTest = { path: string; context: { config: { rootDir: string } } }

const ROOT_DIR = path.resolve(__dirname, '..')
const TIMINGS: Record<string, number> = parseJSON(fs.readFileSync(path.join(ROOT_DIR, 'nodejs-timings.json'), 'utf8'))

function fakeTest(relativePath: string): FakeTest {
    return { path: path.join(ROOT_DIR, relativePath), context: { config: { rootDir: ROOT_DIR } } }
}

// Every file in the manifest plus a pile of files it knows nothing about, which is what the
// sequencer sees in practice — the manifest only carries suites slow enough to steer the packing.
const TESTS: FakeTest[] = [
    ...Object.keys(TIMINGS).map(fakeTest),
    ...Array.from({ length: 400 }, (_, i) => fakeTest(`src/generated/unknown-${i}.test.ts`)),
]

describe('test-sequencer', () => {
    let sequencer: { shard: (tests: FakeTest[], options: { shardIndex: number; shardCount: number }) => FakeTest[] }

    beforeEach(() => {
        sequencer = new BalancedSequencer()
    })

    const partition = (shardCount: number): FakeTest[][] =>
        Array.from({ length: shardCount }, (_, i) => sequencer.shard(TESTS, { shardIndex: i + 1, shardCount }))

    // A packer that drops a file makes CI silently stop running it while still reporting green,
    // and one that duplicates a file runs it twice under different DB state.
    it.each([1, 2, 3, 6, 12])('partitions every test file exactly once across %i shards', (shardCount) => {
        const assigned = partition(shardCount)
            .flat()
            .map((test) => test.path)

        expect(assigned).toHaveLength(TESTS.length)
        expect(new Set(assigned).size).toBe(TESTS.length)
    })

    it('assigns the same files regardless of the order tests are discovered in', () => {
        const reversed = [...TESTS].reverse()

        for (let shardIndex = 1; shardIndex <= 6; shardIndex++) {
            const fromOriginal = sequencer.shard(TESTS, { shardIndex, shardCount: 6 }).map((t) => t.path)
            const fromReversed = sequencer.shard(reversed, { shardIndex, shardCount: 6 }).map((t) => t.path)

            expect(new Set(fromReversed)).toEqual(new Set(fromOriginal))
        }
    })

    // The whole point: no shard may be an outlier, or the job waits on it while the rest idle.
    it('keeps the slowest shard close to the mean', () => {
        const weights = partition(6).map((shard) =>
            shard.reduce((total, test) => total + (TIMINGS[path.relative(ROOT_DIR, test.path)] ?? 0), 0)
        )
        const mean = weights.reduce((a, b) => a + b, 0) / weights.length

        expect(Math.max(...weights) / mean).toBeLessThan(1.2)
    })

    it('falls back to default sharding when the manifest cannot be read', () => {
        jest.spyOn(fs, 'readFileSync').mockImplementation(() => {
            throw new Error('ENOENT')
        })

        const assigned = partition(6)
            .flat()
            .map((test) => test.path)

        expect(new Set(assigned).size).toBe(TESTS.length)
    })
})
