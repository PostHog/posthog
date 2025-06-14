import { PluginEvent, Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { KafkaProducerWrapper } from '../../../kafka/producer'
import { Team } from '../../../types'
import { PersonsStoreForBatch } from './persons-store-for-batch'

/**
 * Lightweight data holder containing all the context needed for person processing.
 * This replaces the previous PersonState class which mixed data and business logic.
 */
export class PersonContext {
    public readonly eventProperties: Properties
    public updateIsIdentified: boolean = false

    constructor(
        public readonly event: PluginEvent,
        public readonly team: Team,
        public readonly distinctId: string,
        public readonly timestamp: DateTime,
        public readonly processPerson: boolean, // $process_person_profile flag from the event
        public readonly kafkaProducer: KafkaProducerWrapper,
        public readonly personStore: PersonsStoreForBatch,
        public readonly measurePersonJsonbSize: number = 0,
        public readonly useOptimizedJSONBUpdates: number = 0.0
    ) {
        this.eventProperties = event.properties!
    }
}
