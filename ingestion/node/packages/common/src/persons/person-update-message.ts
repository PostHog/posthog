import { PERSONS_OUTPUT } from '@posthog/node-common/outputs/index'
import { BasePerson, InternalPerson, RawPerson, TimestampFormat } from '@posthog/node-common/types'
import { castTimestampOrNow } from '@posthog/node-common/utils/utils'

import { PersonMessage } from '~/persons/person-message'

export function unparsePersonPartial(person: Partial<InternalPerson>): Partial<RawPerson> {
    return {
        ...(person as BasePerson),
        ...(person.created_at ? { created_at: person.created_at.toISO() ?? undefined } : {}),
        ...(person.last_seen_at !== undefined ? { last_seen_at: person.last_seen_at?.toISO() ?? null } : {}),
    }
}

// Deletion call sites own the version they emit (the exact stamped death version
// for tombstones), so a deletion must state it explicitly — a stale person.version
// can never become a no-headroom death row.
export function generateKafkaPersonUpdateMessage(person: InternalPerson, isDeleted?: false): PersonMessage
export function generateKafkaPersonUpdateMessage(
    person: InternalPerson,
    isDeleted: true,
    deletedVersion: number
): PersonMessage
export function generateKafkaPersonUpdateMessage(
    person: InternalPerson,
    isDeleted = false,
    deletedVersion?: number
): PersonMessage {
    return {
        output: PERSONS_OUTPUT,
        value: Buffer.from(
            JSON.stringify({
                id: person.uuid,
                created_at: castTimestampOrNow(person.created_at, TimestampFormat.ClickHouseSecondPrecision),
                properties: JSON.stringify(person.properties),
                team_id: person.team_id,
                is_identified: Number(person.is_identified),
                is_deleted: Number(isDeleted),
                version: isDeleted ? deletedVersion : person.version,
                last_seen_at: person.last_seen_at
                    ? castTimestampOrNow(person.last_seen_at, TimestampFormat.ClickHouseSecondPrecision)
                    : null,
            })
        ),
    }
}
