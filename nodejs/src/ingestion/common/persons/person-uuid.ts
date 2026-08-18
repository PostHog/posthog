import { parse as parseUuid, v5 as uuidv5 } from 'uuid'

// UUIDv5 requires a namespace, which is itself a UUID. This was a randomly generated UUIDv4
// that must be used to deterministrically generate UUIDv5s for Person rows.
const PERSON_UUIDV5_NAMESPACE = parseUuid('932979b4-65c3-4424-8467-0b66ec27bc22')

// Another randomly generated UUIDv4, namespacing lifecycle op ids.
const LIFECYCLE_OP_UUIDV5_NAMESPACE = parseUuid('943363e7-16d0-44e1-8c51-ba2c35f6e6a0')

export function uuidFromDistinctId(teamId: number, distinctId: string): string {
    // Deterministcally create a UUIDv5 based on the (team_id, distinct_id) pair.
    return uuidv5(`${teamId}:${distinctId}`, PERSON_UUIDV5_NAMESPACE)
}

// Lifecycle op ids are deterministic per (team_id, event uuid): concurrent deliveries of
// the same event collide on the op PK, while a client-pinned event uuid cannot address
// another team's ops.
export function lifecycleOpIdFromEvent(teamId: number, eventUuid: string): string {
    return uuidv5(`${teamId}:${eventUuid}`, LIFECYCLE_OP_UUIDV5_NAMESPACE)
}

/**
 * The merge saga's idempotency key. The saga freezes the request behind
 * this key and rejects any later call that presents the same key with a
 * different frozen request, so a folded merge and the single-source merges
 * it falls back to must not share one — they are different operations on
 * the same event.
 *
 * The sources enter in request order, because the saga compares them in
 * order: two calls that differ only in order are different merges to it,
 * and giving them one key would make the second a permanent
 * FAILED_PRECONDITION instead of a fresh op that converges as a no-op.
 * Fold plans are batch-deterministic, so a redelivery presents the same
 * order and derives the same key. Each id is length-prefixed so the
 * encoding is injective — a comma inside a distinct id cannot make two
 * different source lists read as one.
 */
export function mergeOpIdFromRequest(
    teamId: number,
    eventUuid: string,
    sourceDistinctIds: string[],
    moveLimit: number
): string {
    // The move limit is part of the op's identity: skipped_move_limit is a
    // recorded verdict, so a redirected async re-attempt running with a
    // raised limit must derive a fresh op rather than attach to the skip
    // it exists to overcome. Same-limit retries still replay.
    const sources = sourceDistinctIds.map((distinctId) => `${distinctId.length}:${distinctId}`).join(',')
    return uuidv5(`${teamId}:${eventUuid}:${moveLimit}:${sources}`, LIFECYCLE_OP_UUIDV5_NAMESPACE)
}

/**
 * A stable fingerprint of the payload fields the replay guard compares but
 * the op id excludes. A FAILED_PRECONDITION retry salts its op id with
 * this: within one delivery the fingerprint is constant, so retries attach
 * to whatever the salted op recorded, and a later delivery whose payload
 * drifted (GeoIP refresh, transformation stamp) derives a different salt —
 * a fresh op that converges as a no-op when the recorded merge committed.
 * A counter-based salt cannot do this: it restarts every delivery, so a
 * few drifted redeliveries exhaust the reachable ids and wedge forever.
 */
export function mergePayloadFingerprint(
    eventSet: Record<string, unknown>,
    eventSetOnce: Record<string, unknown>,
    createdAtMs: number
): string {
    const payload = `${createdAtMs}:${JSON.stringify(eventSet)}:${JSON.stringify(eventSetOnce)}`
    return uuidv5(payload, LIFECYCLE_OP_UUIDV5_NAMESPACE).slice(0, 8)
}
