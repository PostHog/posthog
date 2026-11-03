describe('dashboardMountedTiles', () => {
    let mod: typeof import('./dashboardMountedTiles')

    beforeEach(() => {
        jest.isolateModules(() => {
            mod = require('./dashboardMountedTiles')
        })
    })

    const mountTiles = (
        count: number
    ): { handles: ReturnType<typeof mod.trackMountedDashboardTile>[]; released: () => number[] } => {
        const releases = Array.from({ length: count }, () => jest.fn())
        const handles = releases.map((release) => mod.trackMountedDashboardTile(release))
        const released = (): number[] => releases.flatMap((release, i) => (release.mock.calls.length ? [i] : []))
        return { handles, released }
    }

    it('keeps every tile up to the limit and releases the tile that left the screen first', () => {
        const { handles, released } = mountTiles(mod.MAX_MOUNTED_DASHBOARD_TILES)
        handles[5].setReleasable(true)
        handles[2].setReleasable(true)
        expect(released()).toEqual([])

        mod.trackMountedDashboardTile(jest.fn())

        expect(released()).toEqual([5])
    })

    it('never releases a tile near the screen or with an open overlay, even past the limit', () => {
        const { handles, released } = mountTiles(mod.MAX_MOUNTED_DASHBOARD_TILES + 3)
        expect(released()).toEqual([])

        handles[7].setReleasable(true)

        expect(released()).toEqual([7])
    })
})
