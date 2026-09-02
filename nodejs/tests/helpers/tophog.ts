import { TopHogRegistry } from '~/ingestion/framework/extensions/tophog'

/** A topHog registry that swallows every record — for tests that assert
 * pipeline output, not metrics. */
export function createNoopTopHog(): TopHogRegistry {
    const recorder = { record: () => {} }
    return {
        registerSum: () => recorder,
        registerMax: () => recorder,
        registerAverage: () => recorder,
    }
}

export type RecordedTopHogMetric = { key: Record<string, string>; value: number }

/** A topHog registry that captures every record per metric name, so tests can
 * assert exactly which keys and values each metric received. */
export function createRecordingTopHog(): {
    registry: TopHogRegistry
    records: Map<string, RecordedTopHogMetric[]>
} {
    const records = new Map<string, RecordedTopHogMetric[]>()
    const recorder = (name: string) => ({
        record: (key: Record<string, string>, value: number) => {
            records.set(name, [...(records.get(name) ?? []), { key, value }])
        },
    })
    return {
        registry: { registerSum: recorder, registerMax: recorder, registerAverage: recorder },
        records,
    }
}
