import { TophogOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { TopHog } from '~/ingestion/framework/tophog'

import { Component } from './scopes'
import { Started } from './scopes/component'

export interface TopHogComponentConfig {
    outputs: IngestionOutputs<TophogOutput>
    pipeline: string
    lane: string
}

/**
 * Lifecycle wrapper for a consumer's TopHog registry. The registry is exposed
 * eagerly via `registry()` so pipeline factories can register metrics before
 * the scope starts; the component owns the flush loop's start/stop.
 *
 * TopHog is deliberately per-consumer, not process-shared: an instance bakes
 * in the pipeline/lane labels its rows are stamped with and flushes through
 * that consumer's outputs, and one server process can run several consumers
 * off the same shared services scope.
 */
export class TopHogComponent implements Component<TopHog> {
    private readonly topHog: TopHog

    constructor(config: TopHogComponentConfig) {
        this.topHog = new TopHog(config)
    }

    registry(): TopHog {
        return this.topHog
    }

    start(): Promise<Started<TopHog>> {
        this.topHog.start()
        return Promise.resolve({ value: this.topHog, stop: () => this.topHog.stop() })
    }
}
