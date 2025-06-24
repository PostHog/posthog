import LRU from 'lru-cache'
import { DateTime } from 'luxon'

import { ONE_HOUR } from '../../../config/constants'
import { Person } from '../../../types'
import { logger } from '../../../utils/logger'
import { uuidFromDistinctId } from '../person-uuid'
import { PersonContext } from './person-context'
import { PersonMergeService } from './person-merge-service'
import { PersonPropertyService } from './person-property-service'

// Tracks whether we know we've already inserted a `posthog_personlessdistinctid` for the given
// (team_id, distinct_id) pair. If we have, then we can skip the INSERT attempt.
// TODO: Move this out of module scope, we don't currently have a clean place (outside of the Hub)
// to stash longer lived objects like caches. For now it's not important.
const PERSONLESS_DISTINCT_ID_INSERTED_CACHE = new LRU<string, boolean>({
    max: 10_000,
    maxAge: ONE_HOUR * 24, // cache up to 24h
    updateAgeOnGet: true,
})

/**
 * Main orchestrator for person processing operations.
 * This class coordinates between PersonPropertyService and PersonMergeService
 * to handle the different person processing flows
 */
export class PersonEventProcessor {
    constructor(
        private context: PersonContext,
        private propertyService: PersonPropertyService,
        private mergeService: PersonMergeService
    ) {}

    async processEvent(): Promise<[Person, Promise<void>]> {
        if (!this.context.processPerson) {
            return await this.handlePersonlessMode()
        }

        // First, handle any identify/alias/merge operations
        const [personFromMerge, identifyOrAliasKafkaAck] = await this.mergeService.handleIdentifyOrAlias()

        if (personFromMerge) {
            // Try to shortcut if we have the person from identify or alias
            try {
                const [updatedPerson, updateKafkaAck] = await this.propertyService.updatePersonProperties(
                    personFromMerge
                )
                return [updatedPerson, Promise.all([identifyOrAliasKafkaAck, updateKafkaAck]).then(() => undefined)]
            } catch (error) {
                // Shortcut didn't work, swallow the error and try normal retry loop below
                logger.debug('🔁', `failed update after adding distinct IDs, retrying`, { error })
            }
        }

        // Handle regular property updates
        const [updatedPerson, updateKafkaAck] = await this.propertyService.handleUpdate()
        return [updatedPerson, Promise.all([identifyOrAliasKafkaAck, updateKafkaAck]).then(() => undefined)]
    }

    private async handlePersonlessMode(): Promise<[Person, Promise<void>]> {
        let existingPerson = await this.context.personStore.fetchForChecking(
            this.context.team.id,
            this.context.distinctId
        )

        if (!existingPerson) {
            // See the comment in `mergeDistinctIds`. We are inserting a row into `posthog_personlessdistinctid`
            // to note that this Distinct ID has been used in "personless" mode. This is necessary
            // so that later, during a merge, we can decide whether we need to write out an override
            // or not.

            const personlessDistinctIdCacheKey = `${this.context.team.id}|${this.context.distinctId}`
            if (!PERSONLESS_DISTINCT_ID_INSERTED_CACHE.get(personlessDistinctIdCacheKey)) {
                const personIsMerged = await this.context.personStore.addPersonlessDistinctId(
                    this.context.team.id,
                    this.context.distinctId
                )

                // We know the row is in PG now, and so future events for this Distinct ID can
                // skip the PG I/O.
                PERSONLESS_DISTINCT_ID_INSERTED_CACHE.set(personlessDistinctIdCacheKey, true)

                if (personIsMerged) {
                    // If `personIsMerged` comes back `true`, it means the `posthog_personlessdistinctid`
                    // has been updated by a merge (either since we called `fetchPerson` above, plus
                    // replication lag). We need to check `fetchPerson` again (this time using the leader)
                    // so that we properly associate this event with the Person we got merged into.
                    existingPerson = await this.context.personStore.fetchForUpdate(
                        this.context.team.id,
                        this.context.distinctId
                    )
                }
            }
        }

        if (existingPerson) {
            const person = existingPerson as Person

            // Ensure person properties don't propagate elsewhere, such as onto the event itself.
            person.properties = {}

            // If the team has opted out then we never force the upgrade.
            const teamHasNotOptedOut = !this.context.team.person_processing_opt_out

            if (teamHasNotOptedOut && this.context.timestamp > person.created_at.plus({ minutes: 1 })) {
                // See documentation on the field.
                //
                // Note that we account for timestamp vs person creation time (with a little
                // padding for good measure) to account for ingestion lag. It's possible for
                // events to be processed after person creation even if they were sent prior
                // to person creation, and the user did nothing wrong in that case.
                person.force_upgrade = true
            }

            return [person, Promise.resolve()]
        }

        // We need a value from the `person_created_column` in ClickHouse. This should be
        // hidden from users for events without a real person, anyway. It's slightly offset
        // from the 0 date (by 5 seconds) in order to assist in debugging by being
        // harmlessly distinct from Unix UTC "0".
        const createdAt = DateTime.utc(1970, 1, 1, 0, 0, 5)

        const fakePerson: Person = {
            team_id: this.context.team.id,
            properties: {},
            uuid: uuidFromDistinctId(this.context.team.id, this.context.distinctId),
            created_at: createdAt,
        }
        return [fakePerson, Promise.resolve()]
    }
}
