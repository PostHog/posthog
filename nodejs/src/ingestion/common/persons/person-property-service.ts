import { PersonPropertiesSizeViolationError } from '~/common/persons/repositories/person-repository'
import { defaultRetryConfig, promiseRetry } from '~/common/utils/retries'
import { InternalPerson } from '~/types'

import { PersonContext } from './person-context'
import { PersonCreateService } from './person-create-service'
import { extractEventOps } from './person-update'

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

        let properties = {}
        let propertiesOnce = {}
        if (this.context.processPerson) {
            properties = this.context.eventProperties['$set']
            propertiesOnce = this.context.eventProperties['$set_once']
        }

        return await this.personCreateService.createPerson(
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
