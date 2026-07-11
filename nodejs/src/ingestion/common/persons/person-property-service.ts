import { PersonPropertiesSizeViolationError } from '~/common/persons/repositories/person-repository'
import { defaultRetryConfig, promiseRetry } from '~/common/utils/retries'
import { InternalPerson } from '~/types'

import { PersonContext } from './person-context'
import { PersonCreateService } from './person-create-service'
import { applyEventPropertyUpdates, computeEventPropertyUpdates } from './person-update'

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
        const [person, propertiesHandled, createKafkaAck] = await this.createOrGetPerson()
        if (propertiesHandled) {
            return [person, createKafkaAck]
        }
        const [updatedPerson, updateKafkaAck] = await this.updatePersonProperties(person)
        return [updatedPerson, Promise.all([createKafkaAck, updateKafkaAck]).then(() => undefined)]
    }

    /**
     * @returns [Person, boolean that indicates if properties were already handled or not, and the
     * Kafka ack for a creation's messages. The produce is started here but not awaited — the ack
     * rides the pipeline's side effects so a backpressured producer can't stall the sequential
     * per-distinct-id lane.]
     */
    private async createOrGetPerson(): Promise<[InternalPerson, boolean, Promise<void>]> {
        const person = await this.context.personStore.fetchForUpdate(this.context.team.id, this.context.distinctId)
        if (person) {
            return [person, false, Promise.resolve()]
        }

        let properties = {}
        let propertiesOnce = {}
        if (this.context.processPerson) {
            properties = this.context.eventProperties['$set']
            propertiesOnce = this.context.eventProperties['$set_once']
        }

        const [createdPerson, created, kafkaMessages] = await this.personCreateService.createPerson(
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

        const kafkaAck = this.context.produceMessages(kafkaMessages)
        // Mark handled in case the retry loop in handleUpdate discards this attempt's ack —
        // consumers that do receive the ack still observe a rejection.
        kafkaAck.catch(() => {})
        return [createdPerson, created, kafkaAck]
    }

    async updatePersonProperties(person: InternalPerson): Promise<[InternalPerson, Promise<void>]> {
        person.properties ||= {}

        // Compute property changes
        const propertyUpdates = computeEventPropertyUpdates(
            this.context.event,
            person.properties,
            this.context.updateAllProperties
        )

        const otherUpdates: Partial<InternalPerson> = {}
        if (this.context.updateIsIdentified && !person.is_identified) {
            otherUpdates.is_identified = true
        }

        if (
            this.context.shouldUpdateLastSeenAt &&
            this.context.eventProperties['$update_person_last_seen_at'] !== false
        ) {
            const roundedTimestamp = this.context.timestamp.startOf('hour')
            if (!person.last_seen_at || roundedTimestamp > person.last_seen_at) {
                otherUpdates.last_seen_at = roundedTimestamp
            }
        }

        // Check if we have any changes to make
        const hasChanges = propertyUpdates.hasChanges || Object.keys(otherUpdates).length > 0
        if (!hasChanges) {
            const [updatedPerson, _] = applyEventPropertyUpdates(propertyUpdates, person)
            return [updatedPerson, Promise.resolve()]
        }

        const [updatedPerson, kafkaMessages] = await this.context.personStore.updatePersonWithPropertiesDiffForUpdate(
            person,
            propertyUpdates.toSet,
            propertyUpdates.toUnset,
            otherUpdates,
            this.context.distinctId,
            propertyUpdates.shouldForceUpdate
        )
        const kafkaAck = this.context.produceMessages(kafkaMessages)
        return [updatedPerson, kafkaAck]
    }

    getContext(): PersonContext {
        return this.context
    }
}
