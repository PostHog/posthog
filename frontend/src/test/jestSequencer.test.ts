const { partition } = require('../../jest.sequencer')

describe('jest.sequencer partition', () => {
    const entries = [
        { key: 'a.test.ts', duration: 100, item: 'a' },
        { key: 'b.test.ts', duration: 60, item: 'b' },
        { key: 'c.test.ts', duration: 40, item: 'c' },
        { key: 'd.test.ts', duration: 30, item: 'd' },
        { key: 'e.test.ts', duration: null, item: 'e' },
    ]

    it('places every test in exactly one shard, heaviest first onto the lightest shard', () => {
        const shards = partition(entries, 2)

        expect(shards).toEqual([
            ['a', 'd'],
            ['b', 'c', 'e'],
        ])
    })

    it('ignores the order the tests were discovered in', () => {
        expect(partition([...entries].reverse(), 2)).toEqual(partition(entries, 2))
    })
})
