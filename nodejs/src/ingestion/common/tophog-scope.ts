import { TophogOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { TopHog } from '~/ingestion/framework/tophog'

import { Scope, extend } from './scopes'

/**
 * Extend a consumer scope with a `topHog` registry component that drains into
 * the scope's outputs.
 *
 * TopHog is deliberately per-consumer, not process-shared: an instance bakes
 * in the pipeline/lane labels its rows are stamped with and flushes through
 * that consumer's outputs, and one server process can run several consumers
 * off the same shared services scope.
 */
export function extendWithTopHog<S extends Record<string, object> & { outputs: IngestionOutputs<TophogOutput> }>(
    scope: Scope<S>,
    name: string,
    config: { INGESTION_PIPELINE: string | null; INGESTION_LANE: string | null }
): Scope<S & { topHog: TopHog }> {
    return extend(scope, `${name}-tophog`, (container, builder) =>
        builder.add('topHog', {
            start: () => {
                const topHog = new TopHog({
                    outputs: container.outputs,
                    pipeline: config.INGESTION_PIPELINE ?? 'unknown',
                    lane: config.INGESTION_LANE ?? 'unknown',
                })
                topHog.start()
                return Promise.resolve({ value: topHog, stop: () => topHog.stop() })
            },
        })
    )
}
