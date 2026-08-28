// Canvas-backed insight vizes are expensive to mount: each one spins up a chart and its backing store.
// When fast scrolling flips several tiles into view in the same frame, mounting every chart at once
// blocks the main thread and freezes the page. This scheduler releases a limited number of canvas
// mounts per animation frame, and holds every mount while a dashboard drag is in progress.

type MountRequest = () => void

const MAX_MOUNTS_PER_FRAME = 1

const queue = new Set<MountRequest>()
let rafHandle: number | null = null
let dragActive = false

function flush(): void {
    rafHandle = null
    if (dragActive) {
        return
    }
    let budget = MAX_MOUNTS_PER_FRAME
    for (const request of queue) {
        if (budget <= 0) {
            break
        }
        queue.delete(request)
        budget--
        request()
    }
    if (queue.size > 0) {
        schedule()
    }
}

function schedule(): void {
    if (rafHandle !== null) {
        return
    }
    rafHandle = requestAnimationFrame(flush)
}

/**
 * Request a slot to mount a canvas viz. The returned callback runs once the scheduler releases the slot.
 * Call the returned function to cancel the request (e.g. when the tile leaves the viewport again).
 */
export function requestInsightVizMount(request: MountRequest): () => void {
    if (typeof requestAnimationFrame === 'undefined') {
        request()
        return () => {}
    }
    queue.add(request)
    schedule()
    return () => {
        queue.delete(request)
    }
}

/** While a dashboard drag runs, hold every pending canvas mount so it doesn't compete with the drag. */
export function setDashboardDragActive(active: boolean): void {
    dragActive = active
    if (!active) {
        schedule()
    }
}
