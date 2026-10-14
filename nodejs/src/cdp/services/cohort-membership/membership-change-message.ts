import { MessageWithoutTopic } from '~/common/kafka/producer'

/** A membership change that Node publishes, outside the cohort stream processor. */
export type PublishedMembershipChange = {
    teamId: number
    cohortId: number
    personId: string
    status: 'entered' | 'left'
    /** In the processor's fixed-width `last_updated` format. */
    version: string
    origin: string
}

/** Keyed by person like the processor's own changes, so one person's changes share a partition. */
export function membershipChangeMessage(change: PublishedMembershipChange): MessageWithoutTopic {
    return {
        key: change.personId,
        value: JSON.stringify({
            team_id: change.teamId,
            cohort_id: change.cohortId,
            person_id: change.personId,
            status: change.status,
            last_updated: change.version,
            origin: change.origin,
        }),
    }
}
