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
 * Lifecycle component for a consumer's TopHog registry: starts the flush loop
 * with the scope, drains and stops it on teardown.
 *
 * TopHog is deliberately per-consumer, not process-shared: an instance bakes
 * in the pipeline/lane labels its rows are stamped with and flushes through
 * that consumer's outputs, and one server process can run several consumers
 * off the same shared services scope.
 */
export class TopHogComponent implements Component<TopHog> {
    constructor(private readonly config: TopHogComponentConfig) {}

    start(): Promise<Started<TopHog>> {
        const topHog = new TopHog(this.config)
        topHog.start()
        return Promise.resolve({ value: topHog, stop: () => topHog.stop() })
    }
}
