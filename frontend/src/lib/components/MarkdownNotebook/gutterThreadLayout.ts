export interface GutterThread {
    anchorTop: number
    height: number
}

/** `threads` must be sorted by `anchorTop`. Nothing goes above `minTop`, where it could not be scrolled to. */
export function stackGutterThreads(
    threads: GutterThread[],
    activeIndex: number,
    minTop: number,
    gap: number
): number[] {
    const pinnedIndex = activeIndex > 0 && activeIndex < threads.length ? activeIndex : 0
    const tops: number[] = []

    let nextAvailableTop = pinnedIndex > 0 ? threads[pinnedIndex].anchorTop : minTop
    for (let index = pinnedIndex; index < threads.length; index++) {
        tops[index] = Math.max(threads[index].anchorTop, nextAvailableTop)
        nextAvailableTop = tops[index] + threads[index].height + gap
    }
    for (let index = pinnedIndex - 1; index >= 0; index--) {
        tops[index] = Math.min(threads[index].anchorTop, tops[index + 1] - threads[index].height - gap)
    }

    if (tops.length && tops[0] < minTop) {
        nextAvailableTop = minTop
        for (let index = 0; index < threads.length; index++) {
            tops[index] = index < pinnedIndex ? nextAvailableTop : Math.max(threads[index].anchorTop, nextAvailableTop)
            nextAvailableTop = tops[index] + threads[index].height + gap
        }
    }
    return tops
}
