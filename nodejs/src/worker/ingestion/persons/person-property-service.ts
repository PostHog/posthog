import { InternalPerson } from '../../../types'
import { defaultRetryConfig, promiseRetry } from '../../../utils/retries'
import { extractGroupKeysForPerson } from '../groups'
import { PersonContext } from './person-context'
import { PersonCreateService } from './person-create-service'
import { applyEventPropertyUpdates, computeEventPropertyUpdates } from './person-update'
import { PersonPropertiesSizeViolationError } from './repositories/person-repository'

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

        // Extract group keys from event for mixed user+group feature flag targeting
        // This allows JOINing persons to groups for blast radius calculation
        if (this.context.groupTypeManager) {
            const groupKeys = await extractGroupKeysForPerson(
                this.context.team.id,
                this.context.team.project_id,
                this.context.eventProperties,
                this.context.groupTypeManager
            )
            // Only include group keys that are present in the event
            if (groupKeys.group_0_key !== undefined) {
                otherUpdates.group_0_key = groupKeys.group_0_key
            }
            if (groupKeys.group_1_key !== undefined) {
                otherUpdates.group_1_key = groupKeys.group_1_key
            }
            if (groupKeys.group_2_key !== undefined) {
                otherUpdates.group_2_key = groupKeys.group_2_key
            }
            if (groupKeys.group_3_key !== undefined) {
                otherUpdates.group_3_key = groupKeys.group_3_key
            }
            if (groupKeys.group_4_key !== undefined) {
                otherUpdates.group_4_key = groupKeys.group_4_key
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
        const kafkaAck = this.context.kafkaProducer.queueMessages(kafkaMessages)
        return [updatedPerson, kafkaAck]
    }

    getContext(): PersonContext {
        return this.context
    }
}
