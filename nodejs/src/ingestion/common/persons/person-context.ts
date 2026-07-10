import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import {
    IngestionWarningsOutput,
    PERSON_MERGE_EVENTS_OUTPUT,
    PersonDistinctIdsOutput,
    PersonMergeEventsOutput,
    PersonsOutput,
} from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { PersonMessage } from '~/common/persons/person-message'
import { logger } from '~/common/utils/logger'
import { PluginEvent, Properties } from '~/plugin-scaffold'
import { InternalPerson, Team, ValueMatcher } from '~/types'

import { buildPersonMergeEventMessage } from './person-merge-event'
import { MergeMode } from './person-merge-types'
import { PersonsStoreForBatch } from './persons-store-for-batch'

export const personMergeEventProducedCounter = new Counter({
    name: 'person_merge_event_produced_total',
    help: 'Number of person_merge_events messages acked by the broker (gate-on merges only).',
})

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
     * Best-effort emit of a person_merge_events message for the cohort-stream-processor. No-op when
     * the gate is off or the team is outside the allowlist. Never throws: a produce failure is
     * logged and dropped, so it can never affect ingestion. Delivery is at-most-once; loss is
     * accepted until the delivery-guarantees milestone. The message is explicitly partitioned by
     * `(team_id, P_old)` so it reaches the worker holding P_old's state — see `buildPersonMergeEventMessage`.
     */
    async producePersonMergeEvent(sourcePerson: InternalPerson, targetPerson: InternalPerson): Promise<void> {
        if (!this.shouldProduceMergeEvent()) {
            return
        }
        try {
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
            personMergeEventProducedCounter.inc()
        } catch (error) {
            logger.warn('person_merge_events produce failed, dropping', {
                team_id: this.team.id,
                source_person_uuid: sourcePerson.uuid,
                target_person_uuid: targetPerson.uuid,
                error,
            })
        }
    }
}
