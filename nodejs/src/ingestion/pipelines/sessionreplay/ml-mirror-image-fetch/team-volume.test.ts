import { TeamVolume } from './team-volume'

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
        // The count is read as an order of magnitude, so a few percent of error costs nothing. A
        // set would be exact and would cost hundreds of megabytes at the top of this range.
        const volume = new TeamVolume()
        for (let i = 0; i < teams; i++) {
            volume.record(`team-${i}`)
        }

        const estimate = volume.distinctTeams()

        expect(estimate).toBeGreaterThan(expected * 0.9)
        expect(estimate).toBeLessThan(expected * 1.1)
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
