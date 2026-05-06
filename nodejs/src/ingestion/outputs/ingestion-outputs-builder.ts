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

interface DualWriteDefWithDenylist<
    TK extends string,
    PK extends string,
    STK extends string,
    SPK extends string,
    MK extends string,
    PerK extends string,
    DenyK extends string,
> extends DualWriteDef<TK, PK, STK, SPK, MK, PerK> {
    /** Config key holding a comma-separated list of team IDs that stay on primary in denylist modes. */
    teamDenylistKey: DenyK
}

/** Internal storage shape — denylist key is optional so both variants can share the map. */
type StoredDualWriteDef<SK extends string, PK extends string, NumK extends string> = DualWriteDef<
    SK,
    PK,
    SK,
    PK,
    SK,
    NumK
> & { teamDenylistKey?: SK }

/**
 * Builder for `IngestionOutputs` that validates config keys at compile time.
 *
 * Each `register()` call adds an output name and its config key requirements to the
 * builder's type parameters. `build(registry, config)` then checks that:
 * - The config contains all accumulated topic keys as `string`
 * - The config contains all accumulated producer keys as `P` (the registry's producer name type)
 * - The config contains all accumulated number keys as `number`
 *
 * Use `registerDualWrite()` to enable dual writes for an output with percentage-based modes
 * (`off`, `copy`, `move`). Use `registerDualWriteWithDenylist()` for outputs that also need
 * team-denylist routing (`copy_team_denylist`, `move_team_denylist`) — the denylist key is
 * required in the signature, so it cannot be omitted by mistake.
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
    /** Accumulated config keys with string values (topics, mode, team denylist). */
    StringKey extends string = never,
    /** Accumulated config keys with producer-name values. */
    ProducerKey extends string = never,
    /** Accumulated config keys with numeric values (percentage). */
    NumberKey extends string = never,
> {
    constructor(
        private readonly primaryDefs: Map<string, PrimaryDef<StringKey, ProducerKey>> = new Map(),
        private readonly dualWriteDefs: Map<string, StoredDualWriteDef<StringKey, ProducerKey, NumberKey>> = new Map()
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
     * Register an output with primary and secondary config key pairs for dual writes,
     * using percentage-based routing modes (`off`, `copy`, `move`).
     *
     * The mode key controls routing behavior. For `copy`/`move`, the percentage key controls
     * what fraction of messages (by key hash) are routed to secondary. Use
     * `registerDualWriteWithDenylist()` instead if the output needs `*_team_denylist` modes.
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
            StoredDualWriteDef<StringKey | NewTK | NewSTK | NewMK, ProducerKey | NewPK | NewSPK, NumberKey | NewPerK>
        >(this.dualWriteDefs)
        duals.set(name, definition)
        return new IngestionOutputsBuilder(this.primaryDefs, duals)
    }

    /**
     * Register a dual-write output that also supports team-denylist routing modes
     * (`copy_team_denylist`, `move_team_denylist`).
     *
     * `teamDenylistKey` is required in the signature — this is what makes the config complete
     * at the type level. Team IDs in the denylist stay on primary; other teams go to secondary
     * (move) or both (copy). Messages without a `teamId` stay on primary.
     */
    registerDualWriteWithDenylist<
        Name extends string,
        NewTK extends string,
        NewPK extends string,
        NewSTK extends string,
        NewSPK extends string,
        NewMK extends string,
        NewPerK extends string,
        NewDenyK extends string,
    >(
        name: Name & (Name extends O ? never : Name),
        definition: DualWriteDefWithDenylist<NewTK, NewPK, NewSTK, NewSPK, NewMK, NewPerK, NewDenyK>
    ): IngestionOutputsBuilder<
        O | Name,
        StringKey | NewTK | NewSTK | NewMK | NewDenyK,
        ProducerKey | NewPK | NewSPK,
        NumberKey | NewPerK
    > {
        const duals = new Map<
            string,
            StoredDualWriteDef<
                StringKey | NewTK | NewSTK | NewMK | NewDenyK,
                ProducerKey | NewPK | NewSPK,
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
                const usesDenylist = mode === 'copy_team_denylist' || mode === 'move_team_denylist'
                if (usesDenylist && !def.teamDenylistKey) {
                    throw new Error(`Output "${name}" uses mode "${mode}" but no teamDenylistKey was registered`)
                }
                const teamDenylist = def.teamDenylistKey
                    ? parseTeamDenylist(config[def.teamDenylistKey])
                    : new Set<number>()
                if (usesDenylist && teamDenylist.size === 0) {
                    // An empty denylist in denylist mode would silently route all identifiable-team
                    // traffic to the secondary cluster — fail loudly so a blank/misconfigured env
                    // var is caught at startup rather than in a partial outage.
                    throw new Error(
                        `Output "${name}" uses mode "${mode}" but the team denylist is empty — ` +
                            `all team-attributed traffic would be routed to secondary. Provide at least one team ID.`
                    )
                }
                record[name] = new DualWriteIngestionOutput(
                    primary,
                    new SingleIngestionOutput(
                        name,
                        config[def.secondaryTopicKey],
                        registry.getProducer(secondaryProducerName),
                        secondaryProducerName
                    ),
                    mode,
                    percentage,
                    teamDenylist
                )
            }
        }

        // TypeScript cannot verify that an imperatively-built Record has all keys of a
        // generic union O. The builder guarantees this: every register() call adds an
        // entry to definitions, and build() resolves all of them.
        return new IngestionOutputs<O>(record as Record<O, IngestionOutput>)
    }
}

/**
 * Parse a comma-separated string of team IDs into a Set.
 *
 * Whitespace around entries is trimmed. Empty and non-integer tokens are skipped;
 * mixed tokens like `"1234abc"` are rejected rather than truncated to `1234`.
 */
export function parseTeamDenylist(raw: string): Set<number> {
    if (!raw.trim()) {
        return new Set()
    }
    const ids = new Set<number>()
    for (const part of raw.split(',')) {
        const trimmed = part.trim()
        if (trimmed === '') {
            continue
        }
        const n = Number(trimmed)
        if (Number.isInteger(n)) {
            ids.add(n)
        }
    }
    return ids
}
