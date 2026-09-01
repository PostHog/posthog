import { create } from '@bufbuild/protobuf'
import { Client, Code, ConnectError } from '@connectrpc/connect'
import { Counter } from 'prom-client'

import {
    GetDistinctIdsForPersonsRequestSchema,
    GetOrCreatePersonByDistinctIdRequestSchema,
    GetPersonsByDistinctIdsRequestSchema,
    MergePersonsRequestSchema,
    MergeSourceOutcome,
    PersonHogIdentity,
} from '~/common/generated/personhog/personhog/identity/v1/identity_pb'
import { PersonPropertiesSizeViolationError } from '~/common/persons/repositories/person-repository'
import { Properties } from '~/plugin-scaffold'
import { InternalPerson } from '~/types'

import { encodeJsonBytes, protoPersonToDomain } from './persons'

/**
 * A single get-or-create key: resolve distinct_id within team_id,
 * creating a person stub when absent. The properties and scalars apply
 * on the creation branch only; an existing person takes its ops through
 * the normal update path. The person UUID derives deterministically from
 * team_id:distinct_id on the identity service's side; no id is supplied
 * here.
 */
export interface GetOrCreatePersonEntry {
    teamId: number
    distinctId: string
    /** Additional distinct ids mapped to the person on the creation branch. */
    extraDistinctIds?: string[]
    /** The event name that triggered this call, forwarded to the leader on creation. */
    eventName: string
    setProperties?: Properties
    setOnceProperties?: Properties
    /** Person created_at on the creation branch, epoch milliseconds. */
    createdAtMs: number
    isIdentified?: boolean
}

/** The identity service rejects batches above this; chunk client-side. */
const IDENTITY_BATCH_SIZE = 250

export interface DistinctIdKey {
    teamId: number
    distinctId: string
}

/** One source pair of a merge saga call. */
export interface MergeSagaSource {
    distinctId: string
    /** The $identify/$create_alias event that contributed this pair; for warning correlation only. */
    eventUuid: string
}

export interface MergeSagaRequest {
    teamId: number
    targetDistinctId: string
    /** Ordered; earlier pairs beat later pairs on property precedence, the target beats all. */
    sources: MergeSagaSource[]
    /** The merge event's $set: overrides on conflict, applied to the survivor. */
    eventSet: Properties
    /** The merge event's $set_once: fills only still-absent keys. */
    eventSetOnce: Properties
    /** Retry key: a repeated call with the same op id returns the recorded outcome. */
    opId: string
    /** $merge_dangerously legally merges already-identified sources; $identify does not. */
    allowIdentifiedSources: boolean
    /** Per-source distinct-id count guard; sources over it come back skipped_move_limit. */
    moveLimit: number
    /** Merge event created_at, epoch millis; consulted only when an unresolved target births a fresh person. */
    createdAtMs: number
    /**
     * The executing event's uuid, stable across retries. Stamped as
     * $creator_event_uuid on a person the merge births, and carried onto
     * the fences the saga installs, where the store classifies refusals
     * by it — a per-delivery value would mis-aim that classification.
     */
    creatorEventUuid: string
}

/**
 * Metadata key on identity's definitive refusals; the value is a reason
 * slug. A refusal carrying it is deterministic for the request's exact
 * shape: retrying the same request meets the same answer forever.
 */
export const SEMANTIC_REFUSAL_METADATA_KEY = 'x-semantic-refusal'
/** The op id belongs to a different recorded merge; refused before any durable work. */
export const SEMANTIC_REFUSAL_OP_ID_REUSED = 'op_id_reused'

export type MergeSagaSourceOutcome =
    | 'merged'
    | 'noop_same_person'
    | 'attached'
    | 'skipped_illegal'
    | 'skipped_already_identified'
    | 'skipped_conflict'
    | 'skipped_move_limit'
    | 'skipped_refused'
    | 'error'
    | 'unknown'

export interface MergeSagaResult {
    /** The surviving person; null only when the target no longer resolves. */
    survivor: InternalPerson | null
    results: {
        sourceDistinctId: string
        outcome: MergeSagaSourceOutcome
        /**
         * The person this verdict destroyed, set only on a merged source:
         * a merged-away person is permanent, so a caller may reconcile
         * cached state against it without re-reading. Every other verdict
         * answers null because the person it would name is still live.
         */
        sourcePersonId: string | null
        /**
         * The server's durability statement: true means no retry can change
         * this outcome, false means a retry under the same op id may.
         */
        settled: boolean
    }[]
}

export const personhogUnknownMergeOutcomeCounter = new Counter({
    name: 'personhog_unknown_merge_outcome_total',
    help: 'Merge verdicts this build has no name for, by wire value; a newer identity service can introduce one',
    labelNames: ['wire_value'],
})

const MERGE_OUTCOME_NAMES: Record<MergeSourceOutcome, MergeSagaSourceOutcome> = {
    // Proto3 reads an omitted field as zero, so this says the server sent no
    // verdict rather than that it refused the source.
    [MergeSourceOutcome.UNSPECIFIED]: 'unknown',
    [MergeSourceOutcome.MERGED]: 'merged',
    [MergeSourceOutcome.NOOP_SAME_PERSON]: 'noop_same_person',
    [MergeSourceOutcome.ATTACHED]: 'attached',
    [MergeSourceOutcome.SKIPPED_ILLEGAL]: 'skipped_illegal',
    [MergeSourceOutcome.SKIPPED_ALREADY_IDENTIFIED]: 'skipped_already_identified',
    [MergeSourceOutcome.SKIPPED_CONFLICT]: 'skipped_conflict',
    [MergeSourceOutcome.SKIPPED_MOVE_LIMIT]: 'skipped_move_limit',
    [MergeSourceOutcome.SKIPPED_REFUSED]: 'skipped_refused',
    [MergeSourceOutcome.ERROR]: 'error',
}

/**
 * The name this build knows for a wire verdict. An identity service a
 * release ahead can answer something this build has never heard of, which is
 * not a refusal and must not be recorded as one.
 */
function namedOutcome(wire: MergeSourceOutcome): MergeSagaSourceOutcome {
    const named = MERGE_OUTCOME_NAMES[wire]
    if (named !== undefined) {
        return named
    }
    personhogUnknownMergeOutcomeCounter.labels({ wire_value: String(wire) }).inc()
    return 'unknown'
}

/**
 * The identity service's client wrapper: proto encoding and domain
 * decoding for distinct-id resolution, expansion, and person stub
 * creation. Callers never see proto types or gRPC codes through this
 * surface.
 */
export class PersonhogIdentityOperations {
    constructor(
        private client: Client<typeof PersonHogIdentity>,
        private options: { mergeTimeoutMs?: number } = {}
    ) {}

    /**
     * Resolve-only counterpart of get-or-create: primary-backed
     * resolution, never creates. Results come back in request order;
     * a null person means the distinct id resolves to no live person.
     */
    async getPersonsByDistinctIds(
        keys: DistinctIdKey[],
        callerTag?: string
    ): Promise<{ teamId: number; distinctId: string; person: InternalPerson | null }[]> {
        if (keys.length === 0) {
            return []
        }
        const out: { teamId: number; distinctId: string; person: InternalPerson | null }[] = []
        for (let i = 0; i < keys.length; i += IDENTITY_BATCH_SIZE) {
            const chunk = keys.slice(i, i + IDENTITY_BATCH_SIZE)
            const response = await this.client.getPersonsByDistinctIds(
                create(GetPersonsByDistinctIdsRequestSchema, {
                    keys: chunk.map((key) => ({
                        teamId: BigInt(key.teamId),
                        distinctId: key.distinctId,
                    })),
                }),
                callerTag ? { headers: { 'x-caller-tag': callerTag } } : undefined
            )
            for (const result of response.results) {
                out.push({
                    teamId: Number(result.teamId),
                    distinctId: result.distinctId,
                    person: result.person ? protoPersonToDomain(result.person) : null,
                })
            }
        }
        return out
    }

    /**
     * Person-id to distinct-ids expansion on the primary — the strong
     * twin of the router RPC of the same name. Grouped per person id;
     * with a limit, identified ids survive the cut.
     */
    async getDistinctIdsForPersons(
        teamId: number,
        personIds: string[],
        limitPerPerson?: number,
        callerTag?: string
    ): Promise<Record<string, string[]>> {
        if (personIds.length === 0) {
            return {}
        }
        const byPerson: Record<string, string[]> = {}
        for (let i = 0; i < personIds.length; i += IDENTITY_BATCH_SIZE) {
            const chunk = personIds.slice(i, i + IDENTITY_BATCH_SIZE)
            const response = await this.client.getDistinctIdsForPersons(
                create(GetDistinctIdsForPersonsRequestSchema, {
                    teamId: BigInt(teamId),
                    personIds: chunk.map((id) => BigInt(id)),
                    limitPerPerson: limitPerPerson != null ? BigInt(limitPerPerson) : undefined,
                }),
                callerTag ? { headers: { 'x-caller-tag': callerTag } } : undefined
            )
            for (const group of response.personDistinctIds) {
                byPerson[String(group.personId)] = group.distinctIds.map((d) => d.distinctId)
            }
        }
        return byPerson
    }

    /**
     * Resolves the distinct id to its person, creating a stub when
     * absent. `created` means the stub row is committed in Postgres and
     * any initial properties are durable in the leader's changelog.
     */
    async getOrCreatePersonByDistinctId(
        entry: GetOrCreatePersonEntry,
        callerTag?: string
    ): Promise<{ person: InternalPerson; created: boolean }> {
        try {
            const response = await this.client.getOrCreatePersonByDistinctId(
                create(GetOrCreatePersonByDistinctIdRequestSchema, {
                    entry: {
                        teamId: BigInt(entry.teamId),
                        distinctId: entry.distinctId,
                        extraDistinctIds: entry.extraDistinctIds ?? [],
                        eventName: entry.eventName,
                        setProperties: encodeJsonBytes(entry.setProperties ?? {}),
                        setOnceProperties: encodeJsonBytes(entry.setOnceProperties ?? {}),
                        createdAt: BigInt(entry.createdAtMs),
                        isIdentified: entry.isIdentified ?? false,
                    },
                }),
                callerTag ? { headers: { 'x-caller-tag': callerTag } } : undefined
            )
            if (!response.person) {
                throw new Error(
                    `identity get-or-create returned no person for team ${entry.teamId} distinct_id ${entry.distinctId}`
                )
            }
            return { person: protoPersonToDomain(response.person), created: response.created }
        } catch (error) {
            // A size rejection must surface as the domain error the
            // create service already handles, which emits the customer
            // ingestion warning and stops retrying. Left untranslated,
            // the raw gRPC error matches no non-retriable class and the
            // batch redelivers the same oversized event forever.
            if (error instanceof ConnectError && error.code === Code.InvalidArgument) {
                if (error.rawMessage.includes('size limit')) {
                    throw new PersonPropertiesSizeViolationError(
                        error.rawMessage,
                        entry.teamId,
                        undefined,
                        entry.distinctId
                    )
                }
            }
            throw error
        }
    }

    /**
     * Merge every source distinct id's person into the target's person via
     * the identity service's merge saga. Retries with the same op id return
     * the recorded outcome, so callers reuse the op id across retries.
     */
    async mergePersons(request: MergeSagaRequest, callerTag?: string): Promise<MergeSagaResult> {
        const response = await this.client.mergePersons(
            create(MergePersonsRequestSchema, {
                teamId: BigInt(request.teamId),
                targetDistinctId: request.targetDistinctId,
                sources: request.sources.map((source) => ({
                    sourceDistinctId: source.distinctId,
                    eventUuid: source.eventUuid,
                })),
                eventSet: encodeJsonBytes(request.eventSet),
                eventSetOnce: encodeJsonBytes(request.eventSetOnce),
                opId: request.opId,
                allowIdentifiedSources: request.allowIdentifiedSources,
                moveLimit: BigInt(request.moveLimit),
                createdAt: BigInt(request.createdAtMs),
                creatorEventUuid: request.creatorEventUuid,
            }),
            {
                // A merge drives a multi-step saga rather than a point read,
                // so it gets its own deadline instead of the transport
                // default. It must exceed the engine's
                // lifecycle_execute_timeout_secs so the server answers first
                // in the common case, though a slow step can still outlive
                // this backstop.
                timeoutMs: this.options.mergeTimeoutMs,
                ...(callerTag ? { headers: { 'x-caller-tag': callerTag } } : {}),
            }
        )
        return {
            survivor: response.survivor ? protoPersonToDomain(response.survivor) : null,
            results: response.results.map((result) => ({
                sourceDistinctId: result.sourceDistinctId,
                outcome: namedOutcome(result.outcome),
                sourcePersonId: result.sourcePersonId === undefined ? null : String(result.sourcePersonId),
                settled: result.settled,
            })),
        }
    }
}
