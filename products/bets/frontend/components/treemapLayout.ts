export interface TreemapWeight {
    id: string
    value: number
}

export interface TreemapRectangle extends TreemapWeight {
    x: number
    y: number
    width: number
    height: number
}

export function layoutTreemap(items: TreemapWeight[]): TreemapRectangle[] {
    const visible = items
        .filter((item) => Number.isFinite(item.value) && item.value > 0)
        .sort((a, b) => b.value - a.value || a.id.localeCompare(b.id))
    function partition(
        group: TreemapWeight[],
        x: number,
        y: number,
        width: number,
        height: number
    ): TreemapRectangle[] {
        if (!group.length) {
            return []
        }
        if (group.length === 1) {
            return [{ ...group[0], x, y, width, height }]
        }
        const total = group.reduce((sum, item) => sum + item.value, 0)
        let split = 1
        let weight = group[0].value
        while (
            split < group.length - 1 &&
            Math.abs(weight + group[split].value - total / 2) < Math.abs(weight - total / 2)
        ) {
            weight += group[split++].value
        }
        const fraction = weight / total
        return width >= height
            ? [
                  ...partition(group.slice(0, split), x, y, width * fraction, height),
                  ...partition(group.slice(split), x + width * fraction, y, width * (1 - fraction), height),
              ]
            : [
                  ...partition(group.slice(0, split), x, y, width, height * fraction),
                  ...partition(group.slice(split), x, y + height * fraction, width, height * (1 - fraction)),
              ]
    }
    return partition(visible, 0, 0, 100, 62.5).map((rect) => ({
        ...rect,
        y: rect.y / 0.625,
        height: rect.height / 0.625,
    }))
}
