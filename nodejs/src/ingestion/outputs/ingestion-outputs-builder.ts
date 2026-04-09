import { DualWriteIngestionOutput } from './dual-write-ingestion-output'
import { IngestionOutput } from './ingestion-output'
import { IngestionOutputs } from './ingestion-outputs'
import { KafkaProducerRegistry } from './kafka-producer-registry'
import { SingleIngestionOutput } from './single-ingestion-output'

/**
 * Static definition of an ingestion output — just the config keys for topic and producer.
 *
 * Defaults (topic name, producer name) live in the config object's default values,
 * not in the definition. This keeps definitions pure config-key references.
 */
interface PrimaryDef<TK extends string, PK extends string> {
    topicKey: TK
    producerKey: PK
}

interface DualWriteDef<TK extends string, PK extends string, STK extends string, SPK extends string>
    extends PrimaryDef<TK, PK> {
    secondaryTopicKey: STK
    secondaryProducerKey: SPK
}

/**
 * Builder for `IngestionOutputs` that validates config keys at compile time.
 *
 * Each `register()` call adds an output name and its config key requirements to the
 * builder's type parameters. `build(registry, config)` then checks that:
 * - The config contains all accumulated topic keys as `string`
 * - The config contains all accumulated producer keys as `P` (the registry's producer name type)
 *
 * Use `registerDualWrite()` to enable dual writes for an output — when the config
 * contains non-empty values for both secondary keys, a second target is added.
 *
 * @example
 * ```ts
 * const outputs = new IngestionOutputsBuilder()
 *     .register(EVENTS_OUTPUT, { topicKey: 'OUTPUT_EVENTS_TOPIC', producerKey: 'OUTPUT_EVENTS_PRODUCER' })
 *     .register(DLQ_OUTPUT, { topicKey: 'OUTPUT_DLQ_TOPIC', producerKey: 'OUTPUT_DLQ_PRODUCER' })
 *     .build(registry, config)
 * ```
 */
export class IngestionOutputsBuilder<O extends string = never, TK extends string = never, PK extends string = never> {
    constructor(
        private readonly primaryDefs: Map<string, PrimaryDef<TK, PK>> = new Map(),
        private readonly dualWriteDefs: Map<string, DualWriteDef<TK, PK, TK, PK>> = new Map()
    ) {}

    /**
     * Register an output with its config key pair.
     *
     * The topic and producer config keys are accumulated in the builder's type parameters
     * and checked against the config object when `build()` is called.
     */
    register<Name extends string, NewTK extends string, NewPK extends string>(
        name: Name & (Name extends O ? never : Name),
        definition: PrimaryDef<NewTK, NewPK>
    ): IngestionOutputsBuilder<O | Name, TK | NewTK, PK | NewPK> {
        const primaries = new Map<string, PrimaryDef<TK | NewTK, PK | NewPK>>(this.primaryDefs)
        primaries.set(name, definition)
        return new IngestionOutputsBuilder(primaries, this.dualWriteDefs)
    }

    /**
     * Register an output with primary and secondary config key pairs for dual writes.
     *
     * When both secondary topic and producer are non-empty in the config at build time,
     * produces will fan out to both targets. Otherwise falls back to single output.
     */
    registerDualWrite<
        Name extends string,
        NewTK extends string,
        NewPK extends string,
        NewSTK extends string,
        NewSPK extends string,
    >(
        name: Name & (Name extends O ? never : Name),
        definition: DualWriteDef<NewTK, NewPK, NewSTK, NewSPK>
    ): IngestionOutputsBuilder<O | Name, TK | NewTK | NewSTK, PK | NewPK | NewSPK> {
        const duals = new Map<
            string,
            DualWriteDef<TK | NewTK | NewSTK, PK | NewPK | NewSPK, TK | NewTK | NewSTK, PK | NewPK | NewSPK>
        >(this.dualWriteDefs)
        duals.set(name, definition)
        return new IngestionOutputsBuilder(this.primaryDefs, duals)
    }

    /**
     * Resolve all registered outputs from the registry and config.
     *
     * The compiler verifies that the config contains all accumulated topic keys as `string`
     * and all accumulated producer keys as `P` (matching the registry's producer name type).
     */
    build<P extends string>(
        registry: KafkaProducerRegistry<P>,
        config: Record<TK, string> & Record<PK, P>
    ): IngestionOutputs<O> {
        const record: Record<string, IngestionOutput> = {}

        for (const [name, def] of this.primaryDefs) {
            const producerName = config[def.producerKey]
            record[name] = new SingleIngestionOutput(
                name,
                config[def.topicKey],
                registry.getProducer(producerName),
                producerName
            )
        }

        for (const [name, def] of this.dualWriteDefs) {
            const producerName = config[def.producerKey]
            const primary = new SingleIngestionOutput(
                name,
                config[def.topicKey],
                registry.getProducer(producerName),
                producerName
            )

            const secondaryTopic = config[def.secondaryTopicKey]
            if (secondaryTopic) {
                const secondaryProducerName = config[def.secondaryProducerKey]
                record[name] = new DualWriteIngestionOutput(
                    primary,
                    new SingleIngestionOutput(
                        name,
                        secondaryTopic,
                        registry.getProducer(secondaryProducerName),
                        secondaryProducerName
                    )
                )
            } else {
                record[name] = primary
            }
        }

        // TypeScript cannot verify that an imperatively-built Record has all keys of a
        // generic union O. The builder guarantees this: every register() call adds an
        // entry to definitions, and build() resolves all of them.
        return new IngestionOutputs<O>(record as Record<O, IngestionOutput>)
    }
}
