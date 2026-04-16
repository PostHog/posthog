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

interface DualWriteDef<
    TK extends string,
    PK extends string,
    STK extends string,
    SPK extends string,
    MK extends string,
    PerK extends string,
> extends PrimaryDef<TK, PK> {
    secondaryTopicKey: STK
    secondaryProducerKey: SPK
    modeKey: MK
    percentageKey: PerK
}

/**
 * Builder for `IngestionOutputs` that validates config keys at compile time.
 *
 * Each `register()` call adds an output name and its config key requirements to the
 * builder's type parameters. `build(registry, config)` then checks that:
 * - The config contains all accumulated topic keys as `string`
 * - The config contains all accumulated producer keys as `P` (the registry's producer name type)
 * - The config contains all accumulated number keys as `number`
 *
 * Use `registerDualWrite()` to enable dual writes for an output — the mode and percentage
 * config keys control routing behavior at build time.
 *
 * @example
 * ```ts
 * const outputs = new IngestionOutputsBuilder()
 *     .register(EVENTS_OUTPUT, { topicKey: 'OUTPUT_EVENTS_TOPIC', producerKey: 'OUTPUT_EVENTS_PRODUCER' })
 *     .register(DLQ_OUTPUT, { topicKey: 'OUTPUT_DLQ_TOPIC', producerKey: 'OUTPUT_DLQ_PRODUCER' })
 *     .build(registry, config)
 * ```
 */
export class IngestionOutputsBuilder<
    O extends string = never,
    /** Accumulated config keys with string values (topics, mode). */
    StringKey extends string = never,
    /** Accumulated config keys with producer-name values. */
    ProducerKey extends string = never,
    /** Accumulated config keys with numeric values (percentage). */
    NumberKey extends string = never,
> {
    constructor(
        private readonly primaryDefs: Map<string, PrimaryDef<StringKey, ProducerKey>> = new Map(),
        private readonly dualWriteDefs: Map<
            string,
            DualWriteDef<StringKey, ProducerKey, StringKey, ProducerKey, StringKey, NumberKey>
        > = new Map()
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
    ): IngestionOutputsBuilder<O | Name, StringKey | NewTK, ProducerKey | NewPK, NumberKey> {
        const primaries = new Map<string, PrimaryDef<StringKey | NewTK, ProducerKey | NewPK>>(this.primaryDefs)
        primaries.set(name, definition)
        return new IngestionOutputsBuilder(primaries, this.dualWriteDefs)
    }

    /**
     * Register an output with primary and secondary config key pairs for dual writes.
     *
     * The mode key controls routing behavior (`off`, `copy`, `move`).
     * The percentage key controls what fraction of messages (by key hash) are routed to secondary.
     */
    registerDualWrite<
        Name extends string,
        NewTK extends string,
        NewPK extends string,
        NewSTK extends string,
        NewSPK extends string,
        NewMK extends string,
        NewPerK extends string,
    >(
        name: Name & (Name extends O ? never : Name),
        definition: DualWriteDef<NewTK, NewPK, NewSTK, NewSPK, NewMK, NewPerK>
    ): IngestionOutputsBuilder<
        O | Name,
        StringKey | NewTK | NewSTK | NewMK,
        ProducerKey | NewPK | NewSPK,
        NumberKey | NewPerK
    > {
        const duals = new Map<
            string,
            DualWriteDef<
                StringKey | NewTK | NewSTK | NewMK,
                ProducerKey | NewPK | NewSPK,
                StringKey | NewTK | NewSTK | NewMK,
                ProducerKey | NewPK | NewSPK,
                StringKey | NewTK | NewSTK | NewMK,
                NumberKey | NewPerK
            >
        >(this.dualWriteDefs)
        duals.set(name, definition)
        return new IngestionOutputsBuilder(this.primaryDefs, duals)
    }

    /**
     * Resolve all registered outputs from the registry and config.
     *
     * The compiler verifies that the config contains all accumulated topic keys as `string`,
     * all accumulated producer keys as `P` (matching the registry's producer name type),
     * and all accumulated number keys as `number`.
     */
    build<P extends string>(
        registry: KafkaProducerRegistry<P>,
        config: Record<StringKey, string> & Record<ProducerKey, P> & Record<NumberKey, number>
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

            const mode = config[def.modeKey]
            if (mode === 'off') {
                record[name] = primary
            } else {
                const secondaryProducerName = config[def.secondaryProducerKey]
                const percentage = config[def.percentageKey]
                record[name] = new DualWriteIngestionOutput(
                    primary,
                    new SingleIngestionOutput(
                        name,
                        config[def.secondaryTopicKey],
                        registry.getProducer(secondaryProducerName),
                        secondaryProducerName
                    ),
                    mode,
                    percentage
                )
            }
        }

        // TypeScript cannot verify that an imperatively-built Record has all keys of a
        // generic union O. The builder guarantees this: every register() call adds an
        // entry to definitions, and build() resolves all of them.
        return new IngestionOutputs<O>(record as Record<O, IngestionOutput>)
    }
}
