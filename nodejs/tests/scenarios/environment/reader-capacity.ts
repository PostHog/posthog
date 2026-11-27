import type { MetricPoint } from './metric-data'

export type CapacityMinute = { at: number; max?: number; avg?: number }

export type CapacityLimits = { min: number; max: number; idleMax?: number }

export type CapacityRule = 'unread' | 'over' | 'idle' | 'under' | 'inverted' | 'unshown'

export type CapacityProblem = { rule: CapacityRule; minutes: CapacityMinute[] }

export function capacityMinutesOf(series: {
    max: readonly MetricPoint[]
    avg: readonly MetricPoint[]
}): CapacityMinute[] {
    const byMinute = new Map<number, CapacityMinute>()
    for (const [reading, points] of Object.entries(series)) {
        for (const { at, value } of points) {
            byMinute.set(at, { ...byMinute.get(at), at, [reading]: value })
        }
    }
    return [...byMinute.values()].sort((a, b) => a.at - b.at)
}

const readingsOf = ({ max, avg }: CapacityMinute): number[] =>
    [max, avg].filter((reading): reading is number => reading !== undefined)

// The host before promotion and the controller after the run judge the same minutes by these rules, so a reading
// one of them refuses can never pass the other. `idleSince` is undefined for a warm reader, which skips the idle rules.
export function capacityProblems(
    minutes: readonly CapacityMinute[],
    { min, max, idleMax }: CapacityLimits,
    { idleSince, bothReadings }: { idleSince: number | undefined; bothReadings: boolean }
): CapacityProblem[] {
    const idleWatched = (at: number): boolean => idleSince !== undefined && idleMax !== undefined && at >= idleSince
    const rules: [CapacityRule, (minute: CapacityMinute) => boolean][] = [
        ['unread', (minute) => bothReadings && (minute.max === undefined || minute.avg === undefined)],
        ['over', (minute) => readingsOf(minute).some((reading) => reading > max)],
        ['idle', ({ at, avg }) => idleWatched(at) && avg !== undefined && avg > idleMax!],
        ['under', (minute) => readingsOf(minute).some((reading) => reading < min)],
        ['inverted', ({ max: top, avg }) => top !== undefined && avg !== undefined && avg > top],
        [
            'unshown',
            ({ at, max: top, avg }) => idleWatched(at) && avg === undefined && top !== undefined && top > idleMax!,
        ],
    ]
    return rules
        .map(([rule, fails]) => ({ rule, minutes: minutes.filter(fails) }))
        .filter(({ minutes: failing }) => failing.length > 0)
}
