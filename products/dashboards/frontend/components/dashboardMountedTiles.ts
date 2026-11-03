export const MAX_MOUNTED_DASHBOARD_TILES = 20

type MountedTile = { releasable: boolean; leftAt: number; release: () => void }

export interface MountedTileHandle {
    setReleasable: (releasable: boolean) => void
    untrack: () => void
}

// Small dashboards keep every tile mounted, so scrolling back stays smooth. Past the limit, the tiles that
// left the screen first are released, so a long dashboard does not keep every chart alive after one scroll.
const mounted = new Set<MountedTile>()
let order = 0

function releaseOverflow(): void {
    while (mounted.size > MAX_MOUNTED_DASHBOARD_TILES) {
        let oldest: MountedTile | null = null
        for (const tile of mounted) {
            if (tile.releasable && (!oldest || tile.leftAt < oldest.leftAt)) {
                oldest = tile
            }
        }
        if (!oldest) {
            return
        }
        mounted.delete(oldest)
        oldest.release()
    }
}

export function trackMountedDashboardTile(release: () => void): MountedTileHandle {
    const tile: MountedTile = { releasable: false, leftAt: 0, release }
    mounted.add(tile)
    releaseOverflow()
    return {
        setReleasable: (releasable) => {
            if (releasable && !tile.releasable) {
                // A counter, not a timestamp, so tiles that leave in the same frame keep their order.
                tile.leftAt = ++order
            }
            tile.releasable = releasable
            if (releasable && mounted.has(tile)) {
                releaseOverflow()
            }
        },
        untrack: () => {
            mounted.delete(tile)
        },
    }
}
