import { TeamVolume } from './team-volume'

/**
 * These tests pin the bound, the accounting, and the estimate. They do not pin the count inheritance
 * on eviction, which is the step that guarantees the map always holds a team above total over
 * capacity. A change that drops it makes this a random-eviction cache, which still finds a heavy team
 * often enough that no small test fails.
 */
describe('TeamVolume', () => {
    it('names the busiest teams and sums the rest into one bucket (requirement 29)', () => {
        const volume = new TeamVolume(2)
        volume.record('busiest', 100)
        volume.record('second', 50)
        volume.record('third', 7)
        volume.record('fourth', 3)

        expect(volume.top()).toEqual([
            { team: 'busiest', count: 100 },
            { team: 'second', count: 50 },
            { team: 'other', count: 10 },
        ])
    })

    it('names every team when there are fewer than the limit', () => {
        const volume = new TeamVolume(20)
        volume.record('only', 5)

        // No `other` row: an empty bucket would be a series carrying nothing.
        expect(volume.top()).toEqual([{ team: 'only', count: 5 }])
    })

    it.each([
        [1, 1],
        [10, 10],
        [500, 500],
        [50_000, 50_000],
    ])('estimates %i distinct teams (requirement 30)', (teams, expected) => {
        // A reader takes the order of magnitude, so a few percent of error costs nothing. A set would
        // be exact and would cost hundreds of megabytes at the top of this range.
        const volume = new TeamVolume()
        for (let i = 0; i < teams; i++) {
            volume.record(`team-${i}`)
        }

        const estimate = volume.distinctTeams()

        expect(estimate).toBeGreaterThan(expected * 0.9)
        expect(estimate).toBeLessThan(expected * 1.1)
    })

    it('holds a bounded number of counters however many teams arrive', () => {
        // Someone who spreads traffic over many project tokens must not grow this map for the life
        // of the pod. The map keeps the metric label bounded, so the map must stay bounded itself.
        const volume = new TeamVolume(20)

        for (let i = 0; i < 100_000; i++) {
            volume.record(`team-${i}`)
        }

        expect(volume.trackedTeams).toBeLessThanOrEqual(200)
    })

    it('keeps a busy team named through a flood of teams seen once (requirement 29)', () => {
        // Space-Saving holds any team whose share is above total divided by the counters kept. Here
        // that is 15000 over 20, so 750, and a team at a third of all volume sits far above it.
        // Someone who spreads traffic over many tokens therefore cannot hide a heavy team.
        const volume = new TeamVolume(2)
        volume.record('busy', 5_000)

        for (let i = 0; i < 10_000; i++) {
            volume.record(`noise-${i}`)
        }

        expect(volume.top()[0].team).toBe('busy')
    })

    it('accounts for every URL it was given, named or not', () => {
        const volume = new TeamVolume(2)
        volume.record('a', 10)
        volume.record('b', 5)
        volume.record('c', 3)
        volume.record('d', 2)

        expect(volume.top().reduce((sum, { count }) => sum + count, 0)).toBe(20)
    })

    it('counts a repeated team once', () => {
        const volume = new TeamVolume()
        for (let i = 0; i < 1000; i++) {
            volume.record('same')
        }

        expect(volume.distinctTeams()).toBe(1)
        expect(volume.top()).toEqual([{ team: 'same', count: 1000 }])
    })
})
