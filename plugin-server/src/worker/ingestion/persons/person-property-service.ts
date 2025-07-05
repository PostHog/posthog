import { Histogram } from 'prom-client'

import { InternalPerson } from '../../../types'
import { logger } from '../../../utils/logger'
import { promiseRetry } from '../../../utils/retries'
import { PersonContext } from './person-context'
import { PersonCreateService } from './person-create-service'
import { applyEventPropertyUpdates, computeEventPropertyUpdates } from './person-update'

// temporary: for fetchPerson properties JSONB size observation
const ONE_MEGABYTE_PROPS_BLOB = 1048576
const personPropertiesSize = new Histogram({
    name: 'person_properties_size',
    help: 'histogram of compressed person JSONB bytes retrieved in fetchPerson calls',
    labelNames: ['at'],
    buckets: [1024, 8192, 65536, 524288, 1048576, 2097152, 4194304, 8388608, 16777216, 67108864, Infinity],
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
        return await promiseRetry(() => this.updateProperties(), 'update_person')
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
        await this.capturePersonPropertiesSizeEstimate('createOrGetPerson')

        let person = await this.context.personStore.fetchForUpdate(this.context.team.id, this.context.distinctId)
        if (person) {
            return [person, false]
        }

        let properties = {}
        let propertiesOnce = {}
        if (this.context.processPerson) {
            properties = this.context.eventProperties['$set']
            propertiesOnce = this.context.eventProperties['$set_once']
        }

        person = await this.personCreateService.createPerson(
            this.context.timestamp,
            properties || {},
            propertiesOnce || {},
            this.context.team.id,
            null,
            // :NOTE: This should never be set in this branch, but adding this for logical consistency
            this.context.updateIsIdentified,
            this.context.event.uuid,
            [{ distinctId: this.context.distinctId }]
        )
        return [person, true]
    }

    async updatePersonProperties(person: InternalPerson): Promise<[InternalPerson, Promise<void>]> {
        person.properties ||= {}

        // Compute property changes
        const propertyUpdates = computeEventPropertyUpdates(this.context.event, person.properties)

        const otherUpdates: Partial<InternalPerson> = {}
        if (this.context.updateIsIdentified && !person.is_identified) {
            otherUpdates.is_identified = true
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
            this.context.distinctId
        )
        const kafkaAck = this.context.kafkaProducer.queueMessages(kafkaMessages)
        return [updatedPerson, kafkaAck]
    }

    private async capturePersonPropertiesSizeEstimate(at: string): Promise<void> {
        if (Math.random() >= this.context.measurePersonJsonbSize) {
            // no-op if env flag is set to 0 (default) otherwise rate-limit
            // ramp up of expensive size checking while we test it
            return
        }

        const estimatedBytes: number = await this.context.personStore.personPropertiesSize(
            this.context.team.id,
            this.context.distinctId
        )
        personPropertiesSize.labels({ at: at }).observe(estimatedBytes)

        // if larger than size threshold (start conservative, adjust as we observe)
        // we should log the team and disinct_id associated with the properties
        if (estimatedBytes >= ONE_MEGABYTE_PROPS_BLOB) {
            logger.warn('⚠️', 'record with oversized person properties detected', {
                teamId: this.context.team.id,
                distinctId: this.context.distinctId,
                called_at: at,
                estimated_bytes: estimatedBytes,
            })
        }

        return
    }
}
