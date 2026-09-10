/** Measure elapsed time from a `process.hrtime()` start, rounded to 3 decimal places. */
export function elapsed(startHr: [number, number]): number {
    const [s, ns] = process.hrtime(startHr)
    return Math.round((s + ns / 1e9) * 1000) / 1000
}
