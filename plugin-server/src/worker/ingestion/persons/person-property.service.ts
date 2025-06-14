import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'
import { Histogram } from 'prom-client'

import { InternalPerson, PropertyUpdateOperation } from '../../../types'
import { TransactionClient } from '../../../utils/db/postgres'
import { eventToPersonProperties, initialEventToPersonProperties } from '../../../utils/db/utils'
import { logger } from '../../../utils/logger'
import { promiseRetry } from '../../../utils/retries'
import { uuidFromDistinctId } from '../person-uuid'
import { PersonContext } from './person-context'
import { applyEventPropertyUpdates, applyEventPropertyUpdatesOptimized } from './person-update'

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
    constructor(private context: PersonContext) {}

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
        if (Math.random() < this.context.useOptimizedJSONBUpdates) {
            return await this.updatePersonPropertiesOptimized(person)
        } else {
            return await this.updatePersonProperties(person)
        }
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

        person = await this.createPerson(
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

    private async createPerson(
        createdAt: DateTime,
        properties: Properties,
        propertiesOnce: Properties,
        teamId: number,
        isUserId: number | null,
        isIdentified: boolean,
        creatorEventUuid: string,
        distinctIds: { distinctId: string; version?: number }[],
        tx?: TransactionClient
    ): Promise<InternalPerson> {
        if (distinctIds.length < 1) {
            throw new Error('at least 1 distinctId is required in `createPerson`')
        }
        const uuid = uuidFromDistinctId(teamId, distinctIds[0].distinctId)

        const props = { ...propertiesOnce, ...properties, ...{ $creator_event_uuid: creatorEventUuid } }
        const propertiesLastOperation: Record<string, any> = {}
        const propertiesLastUpdatedAt: Record<string, any> = {}
        Object.keys(propertiesOnce).forEach((key) => {
            propertiesLastOperation[key] = PropertyUpdateOperation.SetOnce
            propertiesLastUpdatedAt[key] = createdAt
        })
        Object.keys(properties).forEach((key) => {
            propertiesLastOperation[key] = PropertyUpdateOperation.Set
            propertiesLastUpdatedAt[key] = createdAt
        })

        const [person, kafkaMessages] = await this.context.personStore.createPerson(
            createdAt,
            props,
            propertiesLastUpdatedAt,
            propertiesLastOperation,
            teamId,
            isUserId,
            isIdentified,
            uuid,
            distinctIds,
            tx
        )

        await this.context.kafkaProducer.queueMessages(kafkaMessages)
        return person
    }

    private async updatePersonPropertiesOptimized(person: InternalPerson): Promise<[InternalPerson, Promise<void>]> {
        person.properties ||= {}

        const propertyUpdate = applyEventPropertyUpdatesOptimized(this.context.event, person.properties)

        const otherUpdates: Partial<InternalPerson> = {}
        if (this.context.updateIsIdentified && !person.is_identified) {
            otherUpdates.is_identified = true
        }

        const hasPropertyChanges =
            propertyUpdate.hasChanges &&
            (Object.keys(propertyUpdate.toSet).length > 0 || propertyUpdate.toUnset.length > 0)
        const hasOtherChanges = Object.keys(otherUpdates).length > 0

        if (hasPropertyChanges || hasOtherChanges) {
            const [updatedPerson, kafkaMessages] =
                await this.context.personStore.updatePersonWithPropertiesDiffForUpdate(
                    person,
                    propertyUpdate.toSet,
                    propertyUpdate.toUnset,
                    otherUpdates,
                    this.context.distinctId
                )
            const kafkaAck = this.context.kafkaProducer.queueMessages(kafkaMessages)
            return [updatedPerson, kafkaAck]
        }

        return [person, Promise.resolve()]
    }

    async updatePersonProperties(person: InternalPerson): Promise<[InternalPerson, Promise<void>]> {
        person.properties ||= {}

        const update: Partial<InternalPerson> = {}
        if (applyEventPropertyUpdates(this.context.event, person.properties)) {
            update.properties = person.properties
        }
        if (this.context.updateIsIdentified && !person.is_identified) {
            update.is_identified = true
        }

        if (Object.keys(update).length > 0) {
            const [updatedPerson, kafkaMessages] = await this.context.personStore.updatePersonForUpdate(
                person,
                update,
                this.context.distinctId
            )
            const kafkaAck = this.context.kafkaProducer.queueMessages(kafkaMessages)
            return [updatedPerson, kafkaAck]
        }

        return [person, Promise.resolve()]
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

    // For tracking what property keys cause us to update persons
    // tracking all properties we add from the event, 'geoip' for '$geoip_*' or '$initial_geoip_*' and 'other' for anything outside of those
    private getMetricKey(key: string): string {
        if (key.startsWith('$geoip_') || key.startsWith('$initial_geoip_')) {
            return 'geoIP'
        }
        if (eventToPersonProperties.has(key)) {
            return key
        }
        if (initialEventToPersonProperties.has(key)) {
            return key
        }
        return 'other'
    }
}
