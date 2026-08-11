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
