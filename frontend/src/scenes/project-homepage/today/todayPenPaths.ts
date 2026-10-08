type Point = [number, number]

function random(seed: string): () => number {
    let state = 2166136261
    for (const character of seed) {
        state = Math.imul(state ^ character.charCodeAt(0), 16777619)
    }
    return () => {
        state = Math.imul(state ^ (state >>> 15), 2246822507)
        state = Math.imul(state ^ (state >>> 13), 3266489909)
        return ((state ^= state >>> 16) >>> 0) / 4294967296
    }
}

function format([x, y]: Point): string {
    return `${x.toFixed(2)} ${y.toFixed(2)}`
}

function smooth(points: Point[]): string {
    let path = `M${format(points[0])}`
    for (let index = 1; index < points.length - 1; index++) {
        const [x, y] = points[index]
        const [nextX, nextY] = points[index + 1]
        path += ` Q${format([x, y])} ${format([(x + nextX) / 2, (y + nextY) / 2])}`
    }
    return `${path} L${format(points[points.length - 1])}`
}

function strokePass(next: () => number, from: number, to: number, height: number): string {
    const tilt = (next() - 0.6) * 2.4
    const wave = (next() - 0.5) * 2.2
    const waves = [0, wave, -wave, 0]
    const points = [0, 0.33, 0.66, 1].map(
        (progress, index): Point => [
            from + (to - from) * progress,
            height + tilt * (progress - 0.5) + waves[index] + (next() - 0.5) * 0.6,
        ]
    )
    const [start, first, second, end] = points.map(format)
    return `M${start} C${first} ${second} ${end}`
}

export function underlinePaths(seed: string): [string, string] {
    const next = random(seed)
    return [
        strokePass(next, 1 + next() * 2, 97 + next() * 2, 4.4),
        strokePass(next, 5 + next() * 6, 92 + next() * 6, 6.6),
    ]
}

const LOOP_SQUARENESS = 0.85

export function circlePath(seed: string): string {
    const next = random(`${seed}-circle`)
    const start = -2.5 + (next() - 0.5) * 0.4
    const sweep = Math.PI * 2 * (1.12 + next() * 0.05)
    const tilt = (next() - 0.5) * 0.08
    const steps = 32
    const points: Point[] = []
    for (let index = 0; index <= steps; index++) {
        const progress = index / steps
        const angle = start + sweep * progress
        const radiusX = 1 - 0.03 * progress + (next() - 0.5) * 0.02
        const radiusY = 1 - 0.12 * progress + (next() - 0.5) * 0.04
        const cos = Math.cos(angle)
        const sin = Math.sin(angle)
        const x = 49 * radiusX * Math.sign(cos) * Math.abs(cos) ** LOOP_SQUARENESS
        const y = 46 * radiusY * Math.sign(sin) * Math.abs(sin) ** LOOP_SQUARENESS
        points.push([50 + x - y * tilt, 50 + y + x * tilt])
    }
    return smooth(points)
}
