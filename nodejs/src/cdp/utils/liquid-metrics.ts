import { Counter, Histogram, metrics as metricsApi } from '@opentelemetry/api'

import { createCounterWithExemplars, createHistogramWithExemplars, swallowing } from '~/common/metrics/instruments'

import type { LiquidRenderBudgetStats, LiquidRenderLimits } from './liquid'

interface LiquidMetrics {
    duration: Histogram
    outputSize: Histogram
    limitCrossings: Counter
}

let instruments: LiquidMetrics | null = null

function getInstruments(): LiquidMetrics {
    if (instruments === null) {
        const meter = metricsApi.getMeter('cdp')
        instruments = {
            duration: createHistogramWithExemplars(meter, 'cdp.liquid.render.duration', {
                description: 'Cumulative time spent rendering Liquid input templates',
                unit: 's',
                advice: { explicitBucketBoundaries: [0.001, 0.005, 0.01, 0.05, 0.1, 0.5] },
            }),
            outputSize: createHistogramWithExemplars(meter, 'cdp.liquid.render.output_size', {
                description: 'Cumulative UTF-8 output size from Liquid input templates',
                unit: 'By',
                advice: { explicitBucketBoundaries: [1024, 16 * 1024, 64 * 1024, 1024 * 1024, 4 * 1024 * 1024] },
            }),
            limitCrossings: createCounterWithExemplars(meter, 'cdp.liquid.render.limit_crossings', {
                description: 'Liquid input render budgets crossed by level and resource',
            }),
        }
    }
    return instruments
}

export const recordLiquidRenderBudget = swallowing(
    (stats: LiquidRenderBudgetStats, limits: LiquidRenderLimits): void => {
        if (!stats.attempted) {
            return
        }

        const { duration, outputSize, limitCrossings } = getInstruments()
        duration.record(stats.renderDurationMs / 1000)
        outputSize.record(stats.outputBytes)

        if (stats.renderDurationMs > limits.softRenderDurationMs) {
            limitCrossings.add(1, { level: 'soft', resource: 'render' })
        }
        if (stats.outputBytes > limits.softOutputBytes) {
            limitCrossings.add(1, { level: 'soft', resource: 'output' })
        }
        if (stats.hardLimit) {
            limitCrossings.add(1, { level: 'hard', resource: stats.hardLimit })
        }
    }
)
