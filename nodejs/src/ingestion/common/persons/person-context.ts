import { DateTime } from 'luxon'

import {
    IngestionWarningsOutput,
    PERSON_MERGE_EVENTS_OUTPUT,
    PersonDistinctIdsOutput,
    PersonMergeEventsOutput,
    PersonsOutput,
} from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { PersonMessage } from '~/common/persons/person-message'
import { PluginEvent, Properties } from '~/plugin-scaffold'
import { InternalPerson, Team, ValueMatcher } from '~/types'

import { buildPersonMergeEventMessage } from './person-merge-event'
import { MergeMode } from './person-merge-types'
import { PersonsStoreForBatch } from './persons-store-for-batch'

export type PersonOutputs = IngestionOutputs<
    PersonsOutput | PersonDistinctIdsOutput | IngestionWarningsOutput | PersonMergeEventsOutput
>

/** Gate + partition-count + team allowlist for the cross-partition merge-event producer. */
export type MergeEventsConfig = {
    enabled: boolean
    partitionCount: number
    /**
     * Matches teams allowed to emit merge events, built from PERSON_MERGE_EVENTS_TEAM_ALLOWLIST
     * (team 2 by default, '*' for all). The no-arg constructor default below matches no teams.
     */
    isTeamEnabled: ValueMatcher<number>
}

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
        public readonly personStore: PersonsStoreForBatch,
        public readonly measurePersonJsonbSize: number = 0,
        public readonly mergeMode: MergeMode,
        public readonly updateAllProperties: boolean = false, // When true, all property changes trigger person updates
        public readonly shouldUpdateLastSeenAt: boolean = false,
        public readonly mergeEventsConfig: MergeEventsConfig = {
            enabled: false,
            partitionCount: 64,
            isTeamEnabled: () => false,
        }
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

    /**
     * Whether a person_merge_events message should be emitted for this context's team. Gated by the
     * global kill switch and scoped to the team allowlist so we do not emit events for teams outside
     * the cohort-stream-processor's scope.
     */
    shouldProduceMergeEvent(): boolean {
        return this.mergeEventsConfig.enabled && this.mergeEventsConfig.isTeamEnabled(this.team.id)
    }

    /**
     * Emit a person_merge_events message for the cohort-stream-processor. Resolved no-op when the
     * gate is off or the team is outside the allowlist. The message is explicitly partitioned by
     * `(team_id, P_old)` so it reaches the worker holding P_old's state — see `buildPersonMergeEventMessage`.
     */
    async producePersonMergeEvent(sourcePerson: InternalPerson, targetPerson: InternalPerson): Promise<void> {
        if (!this.shouldProduceMergeEvent()) {
            return
        }
        const { key, partition, value } = buildPersonMergeEventMessage(
            this.team.id,
            sourcePerson.uuid,
            targetPerson.uuid,
            Date.now(),
            this.mergeEventsConfig.partitionCount
        )
        await this.outputs.produce(PERSON_MERGE_EVENTS_OUTPUT, {
            value,
            key,
            partition,
            teamId: this.team.id,
        })
    }
}
