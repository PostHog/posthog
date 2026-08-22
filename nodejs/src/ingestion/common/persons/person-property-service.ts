import { Counter } from 'prom-client'

import { PersonPropertiesSizeViolationError } from '~/common/persons/repositories/person-repository'
import { defaultRetryConfig, promiseRetry } from '~/common/utils/retries'
import { emitIngestionWarning } from '~/ingestion/common/ingestion-warnings'
import { InternalPerson } from '~/types'

import { PersonContext } from './person-context'
import { PersonCreateService } from './person-create-service'
import { extractEventOps } from './person-update'

export const distinctIdCaseCollisionCheckErrorsCounter = new Counter({
    name: 'distinct_id_case_collision_check_errors_total',
    help: 'Case-collision twin lookups that failed (e.g. persons read replica unavailable) and were skipped so ingestion continues.',
})

/**
 * Service responsible for handling person property updates and person creation.
 * Extracted from PersonState to focus on a single responsibility.
 */
export class PersonPropertyService {
    private personCreateService: PersonCreateService
    constructor(private context: PersonContext) {
        this.personCreateService = new PersonCreateService(context)
    }

    async handleUpdate(): Promise<[InternalPerson, Promise<void>]> {
        // There are various reasons why update can fail:
        // - another thread created the person during a race
        // - the person might have been merged between start of processing and now
        // we simply and stupidly start from scratch
        return await promiseRetry(
            () => this.updateProperties(),
            'update_person',
            defaultRetryConfig.MAX_RETRIES_DEFAULT,
            defaultRetryConfig.RETRY_INTERVAL_DEFAULT,
            undefined,
            [PersonPropertiesSizeViolationError]
        )
    }

    async updateProperties(): Promise<[InternalPerson, Promise<void>]> {
        const [person, propertiesHandled] = await this.createOrGetPerson()
        if (propertiesHandled) {
            return [person, Promise.resolve()]
        }
        return await this.updatePersonProperties(person)
    }

    /**
     * @returns [Person, boolean that indicates if properties were already handled or not]
     */
    private async createOrGetPerson(): Promise<[InternalPerson, boolean]> {
        const person = await this.context.personStore.fetchForUpdate(this.context.team.id, this.context.distinctId)
        if (person) {
            return [person, false]
        }

        // Look up a case-only twin before creating, but hold the warning until the
        // new person actually exists: createPerson can fail permanently (e.g. a
        // person-properties size violation is not retried), and then nothing split.
        const caseTwin = await this.findCaseInsensitiveDistinctIdTwin()

        let properties = {}
        let propertiesOnce = {}
        if (this.context.processPerson) {
            properties = this.context.eventProperties['$set']
            propertiesOnce = this.context.eventProperties['$set_once']
        }

        const created = await this.personCreateService.createPerson(
            this.context.timestamp,
            properties || {},
            propertiesOnce || {},
            this.context.team.id,
            null,
            // :NOTE: This should never be set in this branch, but adding this for logical consistency
            this.context.updateIsIdentified,
            this.context.event.uuid,
            { distinctId: this.context.distinctId }
        )

        if (caseTwin) {
            await this.emitCaseInsensitiveDistinctIdCollisionWarning(caseTwin)
        }

        return created
    }

    /**
     * Find a case-only twin for a fresh distinct id: an existing person under the
     * lowercased form. Returns null when the id is already all-lowercase — so the
     * common path pays no extra read — or when no twin exists.
     *
     * Matching against the lowercased form catches the dominant case where the
     * first-seen twin was already lowercase; a differently-cased twin is not detected.
     */
    private async findCaseInsensitiveDistinctIdTwin(): Promise<InternalPerson | null> {
        const distinctId = this.context.distinctId
        const lowercased = distinctId.toLowerCase()
        if (lowercased === distinctId) {
            return null
        }
        try {
            return await this.context.personStore.fetchForChecking(this.context.team.id, lowercased)
        } catch {
            // This lookup only feeds an info-severity warning, so its failure — e.g. the
            // persons read replica being unavailable — must never fail the event. Count it
            // and skip the warning; person creation continues on the primary as before.
            distinctIdCaseCollisionCheckErrorsCounter.inc()
            return null
        }
    }

    /**
     * Warn that a fresh distinct id created a new person while a lowercased twin
     * already existed for the team. Distinct ids are case-sensitive keys, so the two
     * never merge and the user splits across duplicate persons. The event still
     * ingests normally; this only reports the split.
     */
    private async emitCaseInsensitiveDistinctIdCollisionWarning(twin: InternalPerson): Promise<void> {
        const distinctId = this.context.distinctId
        await emitIngestionWarning(this.context.outputs, this.context.team.id, {
            type: 'distinct_id_case_collision',
            details: {
                distinctId,
                existingDistinctId: distinctId.toLowerCase(),
                personId: twin.uuid,
                eventUuid: this.context.event.uuid,
            },
            pipelineStep: 'person-property',
            key: distinctId,
        })
    }

    async updatePersonProperties(person: InternalPerson): Promise<[InternalPerson, Promise<void>]> {
        person.properties ||= {}

        // The service states the event's intent; what the intent means
        // given current state — diffing, identity OR-merge, last-seen
        // advance, whether anything is worth writing — is the store's
        // concern, resolved against its own world.
        const ops = extractEventOps(this.context.event, this.context.updateAllProperties)
        if (this.context.updateIsIdentified) {
            ops.isIdentified = true
        }
        if (
            this.context.shouldUpdateLastSeenAt &&
            this.context.eventProperties['$update_person_last_seen_at'] !== false
        ) {
            ops.lastSeenAtMs = this.context.timestamp.startOf('hour').toMillis()
        }

        const [updatedPerson, kafkaMessages] = await this.context.personStore.applyEventOps(
            person,
            ops,
            this.context.distinctId
        )
        const kafkaAck = this.context.produceMessages(kafkaMessages)
        return [updatedPerson, kafkaAck]
    }

    getContext(): PersonContext {
        return this.context
    }
}
