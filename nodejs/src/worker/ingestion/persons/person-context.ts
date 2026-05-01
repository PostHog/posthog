import { DateTime } from 'luxon'

import { PluginEvent, Properties } from '~/plugin-scaffold'

import { PersonDistinctIdsOutput, PersonsOutput } from '../../../ingestion/analytics/outputs'
import { IngestionWarningsOutput } from '../../../ingestion/common/outputs'
import { IngestionOutputs } from '../../../ingestion/outputs/ingestion-outputs'
import { Team } from '../../../types'
import { MergeMode } from './person-merge-types'
import { PersonMessage } from './person-message'
import { PersonsStore } from './persons-store'

export type PersonOutputs = IngestionOutputs<PersonsOutput | PersonDistinctIdsOutput | IngestionWarningsOutput>

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
        public readonly outputs: PersonOutputs,
        public readonly personStore: PersonsStore,
        public readonly measurePersonJsonbSize: number = 0,
        public readonly mergeMode: MergeMode,
        public readonly updateAllProperties: boolean = false, // When true, all property changes trigger person updates
        public readonly shouldUpdateLastSeenAt: boolean = false
    ) {
        this.eventProperties = event.properties!
    }

    async produceMessages(messages: PersonMessage[]): Promise<void> {
        await Promise.all(
            messages.map((msg) =>
                this.outputs.produce(msg.output, { value: msg.value, key: null, teamId: this.team.id })
            )
        )
    }
}
