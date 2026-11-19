export interface PlacedItem {
    i: string
    x: number
    y: number
    w: number
    h: number
    minW?: number
}

export interface Gesture {
    activeId: string
    kind: 'drag' | 'resize'
    baseline: PlacedItem[]
}

const DEFAULT_MIN_W = 2

function collides(a: PlacedItem, b: PlacedItem): boolean {
    return a.i !== b.i && a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h
}

function clamp(item: PlacedItem, cols: number): PlacedItem {
    const w = Math.max(1, Math.min(cols, item.w))
    return { ...item, w, x: Math.max(0, Math.min(cols - w, item.x)), y: Math.max(0, item.y) }
}

/**
 * Moves every item up until it meets another, top to bottom, so a grid has no empty rows above a tile.
 * `first` is the tile being moved. It goes ahead of every tile it overlaps, so it keeps the place the pointer
 * gave it and those tiles move down.
 */
function packUp(items: PlacedItem[], first?: string): PlacedItem[] {
    const active = items.find((item) => item.i === first)
    const order = items.filter((item) => item !== active).sort((a, b) => a.y - b.y || a.x - b.x)
    if (active) {
        const at = order.findIndex(
            (other) => collides(active, other) || other.y > active.y || (other.y === active.y && other.x > active.x)
        )
        order.splice(at === -1 ? order.length : at, 0, active)
    }
    const placed: PlacedItem[] = []
    for (const item of order) {
        let y = 0
        for (const other of placed) {
            if (item.x < other.x + other.w && other.x < item.x + item.w) {
                y = Math.max(y, other.y + other.h)
            }
        }
        placed.push({ ...item, y })
    }
    const byId = new Map(placed.map((item) => [item.i, item]))
    return items.map((item) => byId.get(item.i)!)
}

function shrinkToFit(row: PlacedItem[], cols: number): number[] | null {
    const minimums = row.map((item) => Math.min(item.w, item.minW ?? DEFAULT_MIN_W))
    if (minimums.reduce((sum, w) => sum + w, 0) > cols) {
        return null
    }
    const total = row.reduce((sum, item) => sum + item.w, 0)
    const widths = row.map((item, index) => Math.max(minimums[index], Math.floor((item.w * cols) / total)))
    // Rounding and minimums leave the row a few columns over or under.
    let spare = cols - widths.reduce((sum, w) => sum + w, 0)
    while (spare !== 0) {
        const step = Math.sign(spare)
        const candidates = widths
            .map((w, index) => ({ w, index }))
            .filter(({ w, index }) => w + step >= minimums[index] && w + step <= row[index].w)
        if (candidates.length === 0) {
            return null
        }
        // Spare columns go to the narrowest tile and missing ones come off the widest, so the row stays even.
        const pick = candidates.reduce((a, b) => ((step > 0 ? b.w < a.w : b.w > a.w) ? b : a))
        widths[pick.index] += step
        spare -= step
    }
    return widths
}

function joinRow(active: PlacedItem, others: PlacedItem[], rowTop: number, cols: number): PlacedItem[] | null {
    const row = others.filter((item) => item.y <= rowTop && rowTop < item.y + item.h)
    const centre = (item: PlacedItem): number => item.x + item.w / 2
    const members = [...row, { ...active, y: rowTop }].sort((a, b) => centre(a) - centre(b))

    let widths = members.map((item) => item.w)
    if (widths.reduce((sum, w) => sum + w, 0) > cols) {
        const shrunk = shrinkToFit(members, cols)
        if (!shrunk) {
            return null
        }
        widths = shrunk
    }
    // Slide right just far enough to clear the tile before, then back left just far enough to stay in the grid.
    const xs: number[] = []
    let cursor = 0
    members.forEach((item, index) => {
        xs.push(Math.max(item.x, cursor))
        cursor = xs[index] + widths[index]
    })
    let limit = cols
    for (let index = members.length - 1; index >= 0; index--) {
        xs[index] = Math.min(xs[index], limit - widths[index])
        limit = xs[index]
    }
    const moved = new Map(members.map((item, index) => [item.i, { ...item, x: xs[index], w: widths[index] }]))
    return [...others.map((item) => moved.get(item.i) ?? item), moved.get(active.i)!]
}

/**
 * The one rule set for where tiles go in a grid. Without a gesture it only closes gaps. During a gesture every
 * other tile starts from where it was when the gesture began, so the result depends on where the pointer is now
 * and not on the path it took.
 */
export function placeTiles(items: PlacedItem[], cols: number, gesture?: Gesture): PlacedItem[] {
    const current = items.map((item) => clamp(item, cols))
    const moved = gesture && current.find((item) => item.i === gesture.activeId)
    if (!gesture || !moved) {
        return packUp(current)
    }
    const baseline = new Map(gesture.baseline.map((item) => [item.i, item]))
    const start = baseline.get(moved.i)
    // A row can make a dragged tile narrower. It gets its own width back as soon as it leaves that row.
    const active = gesture.kind === 'drag' && start ? clamp({ ...moved, w: start.w, h: start.h }, cols) : moved
    const others = current
        .filter((item) => item.i !== active.i)
        .map((item) => clamp({ ...item, ...baseline.get(item.i), i: item.i }, cols))

    let placed = [...others, active]
    const hit = gesture.kind === 'drag' ? others.filter((other) => collides(active, other)) : []
    if (hit.length > 0) {
        const rowTop = Math.min(...hit.map((item) => item.y))
        const rowHeight = Math.min(...hit.filter((item) => item.y === rowTop).map((item) => item.h))
        if (active.y < rowTop + rowHeight / 2) {
            placed = joinRow(active, others, rowTop, cols) ?? placed
        } else {
            placed = [...others, { ...active, y: bottomOf(hit) }]
        }
    }
    const result = packUp(placed, active.i)
    const byId = new Map(result.map((item) => [item.i, item]))
    return current.map((item) => byId.get(item.i)!)
}

export function bottomOf(items: readonly { y: number; h: number }[]): number {
    return Math.max(0, ...items.map((item) => item.y + item.h))
}
