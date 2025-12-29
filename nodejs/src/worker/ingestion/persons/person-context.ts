import { DateTime } from 'luxon'

import { PluginEvent, Properties } from '@posthog/plugin-scaffold'

import { KafkaProducerWrapper } from '../../../kafka/producer'
import { Team } from '../../../types'
import { MergeMode } from './person-merge-types'
import { PersonsStore } from './persons-store'

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
        public readonly personStore: PersonsStore,
        public readonly measurePersonJsonbSize: number = 0,
        public readonly mergeMode: MergeMode,
        public readonly updateAllProperties: boolean = false // When true, all property changes trigger person updates
    ) {
        this.eventProperties = event.properties!
    }
}
