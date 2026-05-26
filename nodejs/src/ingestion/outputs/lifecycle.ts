import { IngestionOutputs } from './ingestion-outputs'

/**
 * Lifecycle owner for an `IngestionOutputs` derived from already-running
 * infrastructure (typically a shared Kafka producer registry). `start()`
 * resolves the outputs via the `build` callback and verifies that every
 * output's topic is reachable; `stop()` is a no-op because the producer
 * registry's own Manager owns the connection lifetimes.
 */
export class IngestionOutputsLifecycle<O extends string> {
    constructor(private readonly build: () => IngestionOutputs<O>) {}

    async start(): Promise<{ service: IngestionOutputs<O>; stop: () => Promise<void> }> {
        const outputs = this.build()
        const failures = await outputs.checkTopics()
        if (failures.length > 0) {
            throw new Error(`Output topic verification failed for: ${failures.join(', ')}`)
        }
        return { service: outputs, stop: () => Promise.resolve() }
    }
}
