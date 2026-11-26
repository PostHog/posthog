// `FitRow`'s `gap-2`.
export const ITEM_GAP_PX = 8

/**
 * How many items, in order, fit on one line of `available` pixels. When some do not fit, room for the "+N filters"
 * button (`moreWidth`) is kept at the end, so the last item that shows may be one fewer than fits on its own.
 */
export function fitCount(widths: number[], available: number, moreWidth: number): number {
    let used = 0
    for (let index = 0; index < widths.length; index++) {
        const next = used + (index > 0 ? ITEM_GAP_PX : 0) + widths[index]
        const reserve = index < widths.length - 1 ? ITEM_GAP_PX + moreWidth : 0
        if (next + reserve > available) {
            return index
        }
        used = next
    }
    return widths.length
}
