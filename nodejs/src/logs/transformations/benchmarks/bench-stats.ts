export interface BenchStats {
    programId: string
    recordId: string
    meanUs: number
    p50Us: number
    p95Us: number
    p99Us: number
    maxUs: number
}

export function computeBenchStats(programId: string, recordId: string, durationsUs: number[]): BenchStats {
    const sorted = [...durationsUs].sort((a, b) => a - b)
    const pick = (p: number): number => sorted[Math.min(sorted.length - 1, Math.floor((p / 100) * sorted.length))]
    return {
        programId,
        recordId,
        meanUs: sorted.reduce((a, b) => a + b, 0) / sorted.length,
        p50Us: pick(50),
        p95Us: pick(95),
        p99Us: pick(99),
        maxUs: sorted[sorted.length - 1],
    }
}

export function printBenchStatsTable(title: string, iterations: number, allStats: BenchStats[]): void {
    console.info(`\n${title} (${iterations} iterations each, µs):\n`)
    const header = ['program', 'record', 'mean', 'p50', 'p95', 'p99', 'max']
    const rows = allStats.map((s) => [
        s.programId,
        s.recordId,
        s.meanUs.toFixed(1),
        s.p50Us.toFixed(1),
        s.p95Us.toFixed(1),
        s.p99Us.toFixed(1),
        s.maxUs.toFixed(1),
    ])
    const widths = header.map((h, i) => Math.max(h.length, ...rows.map((r) => r[i].length)))
    console.info(header.map((h, i) => h.padEnd(widths[i])).join('  '))
    for (const row of rows) {
        console.info(row.map((c, i) => c.padEnd(widths[i])).join('  '))
    }
}
