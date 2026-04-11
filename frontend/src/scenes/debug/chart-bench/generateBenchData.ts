/**
 * Deterministic synthetic data for the chart bench screen. Shared between the
 * hog-charts and chart.js cells so both libraries render exactly the same
 * numbers — any perf difference is the chart engine, not the input.
 */

export interface BenchData {
    labels: string[]
    series: {
        key: string
        label: string
        data: number[]
    }[]
}

/** Mulberry32 — tiny seeded PRNG, no dependencies, deterministic across runs. */
function mulberry32(seed: number): () => number {
    let a = seed >>> 0
    return () => {
        a = (a + 0x6d2b79f5) >>> 0
        let t = a
        t = Math.imul(t ^ (t >>> 15), t | 1)
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296
    }
}

export function generateBenchData(seriesCount: number, pointCount: number, seed: number): BenchData {
    const rand = mulberry32(seed)

    const labels: string[] = []
    // Daily labels starting from a fixed epoch so the x-axis is identical across runs.
    const epoch = new Date('2024-01-01T00:00:00Z').getTime()
    const dayMs = 24 * 60 * 60 * 1000
    for (let i = 0; i < pointCount; i++) {
        labels.push(new Date(epoch + i * dayMs).toISOString().slice(0, 10))
    }

    const series: BenchData['series'] = []
    for (let s = 0; s < seriesCount; s++) {
        // Each series gets its own baseline, amplitude, phase and noise level —
        // enough variety that stacking/overlap is realistic.
        const baseline = 100 + rand() * 400
        const amplitude = 20 + rand() * 200
        const phase = rand() * Math.PI * 2
        const period = 7 + rand() * 21
        const noiseScale = 10 + rand() * 40

        const data: number[] = []
        for (let i = 0; i < pointCount; i++) {
            const wave = Math.sin((i / period) * Math.PI * 2 + phase) * amplitude
            const noise = (rand() - 0.5) * noiseScale
            data.push(Math.max(0, Math.round(baseline + wave + noise)))
        }

        series.push({
            key: `series-${s}`,
            label: `Series ${s + 1}`,
            data,
        })
    }

    return { labels, series }
}
