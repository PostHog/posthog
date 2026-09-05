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
 * The merge saga's idempotency key. A multi-source fold and its per-source
 * fallback merges derive different ids through the source list, while a
 * single-pair fold deliberately shares its id with its fallback, whose
 * retry then attaches to and resumes the same recorded op. Source order
 * and the length-prefixed encoding are part of the identity, so a comma
 * inside a distinct id cannot make two source lists read as one.
 */
export function mergeOpIdFromRequest(
    teamId: number,
    eventUuid: string,
    targetDistinctId: string,
    sourceDistinctIds: string[],
    moveLimit: number
): string {
    // The move limit is part of the op's identity: a redirected re-attempt
    // with a raised limit must derive a fresh op rather than attach to the
    // recorded skip it exists to overcome. The target is too, so two events
    // sharing a uuid cannot collide across different merges.
    const sources = sourceDistinctIds.map((distinctId) => `${distinctId.length}:${distinctId}`).join(',')
    const target = `${targetDistinctId.length}:${targetDistinctId}`
    return uuidv5(`${teamId}:${eventUuid}:${moveLimit}:${target}:${sources}`, LIFECYCLE_OP_UUIDV5_NAMESPACE)
}
