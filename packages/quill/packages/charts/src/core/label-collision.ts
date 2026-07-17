// Priority-drop collision resolution for absolutely-positioned label boxes. Shared by chart
// types that crowd labels into a tight region (pie slice labels, slope-chart series labels) and
// want the most significant labels to survive rather than letting everything overlap.

export interface LabelBox {
    key: string
    x: number
    y: number
    halfWidth: number
    halfHeight: number
    /** Priority used to resolve collisions — larger values are kept first. */
    value: number
    lines: string[]
}

export function overlaps(a: LabelBox, b: LabelBox): boolean {
    return Math.abs(a.x - b.x) < a.halfWidth + b.halfWidth && Math.abs(a.y - b.y) < a.halfHeight + b.halfHeight
}

/** Keys of the boxes whose centered box doesn't collide with an already-kept one. Higher-`value`
 *  boxes win, so when labels crowd the same region the most significant ones survive and the rest
 *  are dropped rather than overlapping. */
export function nonCollidingKeys(boxes: LabelBox[]): Set<string> {
    const kept: LabelBox[] = []
    const keptKeys = new Set<string>()
    for (const box of [...boxes].sort((a, b) => b.value - a.value)) {
        if (kept.every((other) => !overlaps(box, other))) {
            kept.push(box)
            keptKeys.add(box.key)
        }
    }
    return keptKeys
}
