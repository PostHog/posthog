import { PluginEvent } from '@posthog/plugin-scaffold'
import Sentry from '@sentry/node'
import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { eventDroppedCounter } from '../../main/ingestion-queues/metrics'
import { runInstrumentedFunction } from '../../main/utils'
import { Hub, Person, PersonMode, PipelineEvent, RawKafkaEvent, Team, TimestampFormat } from '../../types'
import { MessageSizeTooLarge } from '../../utils/db/error'
import { safeClickhouseString, sanitizeEventName, sanitizeString } from '../../utils/db/utils'
import { normalizeEvent, normalizeProcessPerson } from '../../utils/event'
import { status } from '../../utils/status'
import { castTimestampOrNow, UUID } from '../../utils/utils'
import { GroupTypeManager, MAX_GROUP_TYPES_PER_TEAM } from '../../worker/ingestion/group-type-manager'
import { PersonState } from '../../worker/ingestion/person-state'
import { upsertGroup } from '../../worker/ingestion/properties-updater'
import { parseEventTimestamp } from '../../worker/ingestion/timestamps'
import { captureIngestionWarning } from '../../worker/ingestion/utils'
import { runProcessEvent } from '../../worker/plugins/run'
import { getElementsChain } from './utils/event-utils'
import { extractHeatmapData } from './utils/heatmaps'

export class EventPipelineHandledError extends Error {
    constructor(public message: string, public ingestion_warning: string) {
        super(message)
    }
}

export const droppedEventFromPluginServerCounter = new Counter({
    name: 'event_pipeline_plugin_dropped_events_total',
    help: 'Count of events dropped by plugins',
})

export class EventPipelineRunnerV2 {
    private team?: Team
    private promises: Promise<any>[] = []
    private event: PluginEvent
    private shouldProcessPerson: boolean = true
    private timestamp?: DateTime
    private person?: Person
    private groupTypeManager: GroupTypeManager

    constructor(private hub: Hub, private originalEvent: PipelineEvent) {
        this.event = {
            ...this.originalEvent,
            properties: {
                ...(this.originalEvent.properties ?? {}),
            },
            team_id: originalEvent.team_id ?? -1,
        }
        this.groupTypeManager = new GroupTypeManager(hub.postgres, hub.teamManager, hub.SITE_URL)
    }

    public getPromises(): Promise<any>[] {
        return this.promises
    }

    private captureIngestionWarning(warning: string, details: Record<string, any> = {}): void {
        this.promises.push(
            captureIngestionWarning(this.hub.kafkaProducer, this.team!.id, warning, {
                eventUuid: JSON.stringify(this.event.uuid),
                event: this.event.event,
                distinctId: this.event.distinct_id,
                ...details,
            })
        )
    }

    private dropEvent(dropCause: string): void {
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: dropCause,
            })
            .inc()
    }

    async run(): Promise<void> {
        // TODO: The parent should handle checking the error and throwing properly once all promises are handled
        try {
            await this._run()
        } catch (error) {
            if (error instanceof EventPipelineHandledError) {
                // Handled errors mean we know that it was invalid and are purposefully moving on - everything else is unhandled
                return this.captureIngestionWarning(error.ingestion_warning)
            }
            // Otherwise rethrow, which leads to Kafka offsets not getting committed and retries
            Sentry.captureException(error, {
                tags: { pipeline_step: 'outside' },
                extra: { originalEvent: this.originalEvent },
            })
            throw error
        }
    }

    private async _run(): Promise<void> {
        // First of all lets get the team
        const team = await this.getTeam()

        if (!team) {
            return this.dropEvent('invalid_token')
        }
        this.event.team_id = team.id

        // Early exit for client ingestion warnings
        if (this.event.event === '$$client_ingestion_warning') {
            this.captureIngestionWarning('client_ingestion_warning', {
                message: this.event.properties?.$$client_ingestion_warning_message,
            })
            return
        }

        this.validateUuid()
        this.validatePersonProcessing()

        // THis is where we cut off for heatmaps...

        if (this.event.event === '$$heatmap') {
            // Heatmaps are not typical events so we bypass alot of the usual processing
            this.normalizeEvent()
            this.extractHeatmapData()
            return
        }

        const pluginProcessed = await this.runPluginProcessing()
        if (!pluginProcessed) {
            droppedEventFromPluginServerCounter.inc()
            // NOTE: In this case we just return as it is expected, not an ingestion error
            return
        }

        this.normalizeEvent()
        await this.processPerson()
        await this.processGroups()

        this.trackFirstEventIngestion()
        this.extractHeatmapData()

        const kafkaEvent = this.createKafkaEvent()

        if (this.event.event === '$exception' && !this.event.properties?.hasOwnProperty('$sentry_event_id')) {
            this.produceExceptionSymbolificationEventStep(kafkaEvent)
            return
        }

        this.produceEventToKafka(kafkaEvent)
    }

    async getTeam(): Promise<Team | null> {
        const { token, team_id } = this.originalEvent
        // Events with no token or team_id are dropped, they should be blocked by capture
        if (team_id) {
            return await this.hub.teamManager.fetchTeam(team_id)
        }
        if (token) {
            // HACK: we've had null bytes end up in the token in the ingest pipeline before, for some reason. We should try to
            // prevent this generally, but if it happens, we should at least simply fail to lookup the team, rather than crashing
            return await this.hub.teamManager.getTeamByToken(sanitizeString(token))
        }

        return null
    }

    private validateUuid(): void {
        // Check for an invalid UUID, which should be blocked by capture, when team_id is present
        if (!UUID.validateString(this.event.uuid, false)) {
            throw new EventPipelineHandledError(`Not a valid UUID: "${this.event.uuid}"`, 'skipping_event_invalid_uuid')
        }
    }

    private validatePersonProcessing() {
        // We allow teams to set the person processing mode on a per-event basis, but override
        // it with the team-level setting, if it's set to opt-out (since this is billing related,
        // we go with preferring not to do the processing even if the event says to do it, if the
        // setting says not to).
        if (this.team!.person_processing_opt_out) {
            this.event.properties!.$process_person_profile = false
        }

        const processPersonProfile = this.event.properties!.$process_person_profile

        if (processPersonProfile === false) {
            if (['$identify', '$create_alias', '$merge_dangerously', '$groupidentify'].includes(this.event.event)) {
                // TODO: Add back in "alwaysSend: true" once we have a way to send events to DLQ
                throw new EventPipelineHandledError(
                    `Invalid event when process_person_profile is false: "${this.event.event}"`,
                    'invalid_event_when_process_person_profile_is_false'
                )
            }
            // If person processing is disabled, go ahead and remove person related keys before
            // any plugins have a chance to see them.
            // NOTE: From refactor - do we actually need to do this?
            this.event = normalizeProcessPerson(this.event, false)
            this.shouldProcessPerson = false
            return
        }

        if (processPersonProfile !== undefined && typeof processPersonProfile !== 'boolean') {
            this.captureIngestionWarning('invalid_process_person_profile', {
                $process_person_profile: processPersonProfile,
            })
        }
    }

    private async runPluginProcessing(): Promise<boolean> {
        const processedEvent = await runInstrumentedFunction({
            timeoutContext: () => ({ event: JSON.stringify(this.event) }),
            func: () => runProcessEvent(this.hub, this.event),
            statsKey: 'kafka_queue.single_event',
            timeoutMessage: 'Still running plugins on event. Timeout warning after 30 sec!',
            teamId: this.event.team_id,
        })

        if (processedEvent) {
            this.event = processedEvent
            return true
        }
        return false
    }

    private normalizeEvent() {
        try {
            this.event.event = sanitizeEventName(this.event.event)
            this.event = normalizeEvent(this.event)
            this.event = normalizeProcessPerson(this.event, this.shouldProcessPerson)
            this.timestamp = parseEventTimestamp(this.event)
        } catch (error) {
            status.warn('⚠️', 'Failed normalizing event', {
                team_id: this.event.team_id,
                uuid: this.event.uuid,
                error,
            })
            throw error
        }
    }

    private trackFirstEventIngestion() {
        // We always track 1st event ingestion
        this.promises.push(this.hub.teamManager.setTeamIngestedEvent(this.team!, this.event.properties!))
    }

    private async processPerson() {
        // NOTE: PersonState could derive so much of this stuff instead of it all being passed in
        const [person, kafkaAck] = await new PersonState(
            this.event,
            this.event.team_id,
            String(this.event.distinct_id),
            this.timestamp!,
            this.shouldProcessPerson,
            this.hub.db
        ).update()

        this.person = person
        this.promises.push(kafkaAck)
    }

    private async processGroups() {
        if (!this.shouldProcessPerson) {
            return
        }

        // Adds group_0 etc values to properties
        for (const [groupType, groupIdentifier] of Object.entries(this.event.properties!.$groups || {})) {
            const columnIndex = await this.groupTypeManager.fetchGroupTypeIndex(
                this.team!.id,
                this.team!.project_id,
                groupType
            )
            if (columnIndex !== null) {
                // :TODO: Update event column instead
                this.event.properties![`$group_${columnIndex}`] = groupIdentifier
            }
        }

        if (this.event.event === '$groupidentify') {
            if (!this.event.properties!['$group_type'] || !this.event.properties!['$group_key']) {
                return
            }

            const {
                $group_type: groupType,
                $group_key: groupKey,
                $group_set: groupPropertiesToSet,
            } = this.event.properties!
            const groupTypeIndex = await this.groupTypeManager.fetchGroupTypeIndex(
                this.team!.id,
                this.team!.project_id,
                groupType
            )

            if (groupTypeIndex !== null) {
                await upsertGroup(
                    this.hub.db,
                    this.team!.id,
                    this.team!.project_id,
                    groupTypeIndex,
                    groupKey.toString(),
                    groupPropertiesToSet || {},
                    this.timestamp!
                )
            }
        }
    }

    private extractHeatmapData() {
        try {
            if (this.team?.heatmaps_opt_in !== false) {
                const heatmapEvents = extractHeatmapData(this.event) ?? []

                this.promises.push(
                    ...heatmapEvents.map((rawEvent) => {
                        return this.hub.kafkaProducer.produce({
                            topic: this.hub.CLICKHOUSE_HEATMAPS_KAFKA_TOPIC,
                            key: this.event.uuid,
                            value: Buffer.from(JSON.stringify(rawEvent)),
                            waitForAck: true,
                        })
                    })
                )
            }
        } catch (e) {
            this.captureIngestionWarning('invalid_heatmap_data', {
                eventUuid: this.event.uuid,
            })
        }

        // We don't want to ingest this data to the events table
        delete this.event.properties!['$heatmap_data']
    }

    private createKafkaEvent(): RawKafkaEvent {
        // Just before we write we can now remove the IP if we need to
        if (this.event.properties!['$ip'] && this.team!.anonymize_ips) {
            delete this.event.properties!['$ip']
        }

        const { properties } = this.event

        let elementsChain = ''
        try {
            elementsChain = getElementsChain(properties!)
        } catch (error) {
            Sentry.captureException(error, { tags: { team_id: this.team!.id } })
            status.warn('⚠️', 'Failed to process elements', {
                uuid: this.event.uuid,
                teamId: this.team!.id,
                properties,
                error,
            })
        }

        let eventPersonProperties = '{}'
        if (this.shouldProcessPerson) {
            eventPersonProperties = JSON.stringify({
                ...this.person!.properties,
                // For consistency, we'd like events to contain the properties that they set, even if those were changed
                // before the event is ingested.
                ...(this.event.properties?.$set || {}),
            })
        } else {
            // TODO: Move this into `normalizeEventStep` where it belongs, but the code structure
            // and tests demand this for now.
            for (let groupTypeIndex = 0; groupTypeIndex < MAX_GROUP_TYPES_PER_TEAM; ++groupTypeIndex) {
                const key = `$group_${groupTypeIndex}`
                delete this.event.properties![key]
            }
        }

        let personMode: PersonMode = 'full'
        if (this.person!.force_upgrade) {
            personMode = 'force_upgrade'
        } else if (!this.shouldProcessPerson) {
            personMode = 'propertyless'
        }

        return {
            uuid: this.event.uuid,
            event: safeClickhouseString(this.event.event),
            properties: JSON.stringify(this.event.properties ?? {}),
            timestamp: castTimestampOrNow(this.timestamp!, TimestampFormat.ClickHouse),
            team_id: this.team!.id,
            project_id: this.team!.project_id,
            distinct_id: safeClickhouseString(this.event.distinct_id),
            elements_chain: safeClickhouseString(elementsChain),
            created_at: castTimestampOrNow(null, TimestampFormat.ClickHouse),
            person_id: this.person!.uuid,
            person_properties: eventPersonProperties,
            person_created_at: castTimestampOrNow(this.person!.created_at, TimestampFormat.ClickHouseSecondPrecision),
            person_mode: personMode,
        }
    }

    private produceExceptionSymbolificationEventStep(event: RawKafkaEvent) {
        this.promises.push(
            this.hub.kafkaProducer
                .produce({
                    topic: this.hub.EXCEPTIONS_SYMBOLIFICATION_KAFKA_TOPIC,
                    key: event.uuid,
                    value: Buffer.from(JSON.stringify(event)),
                    waitForAck: true,
                })
                .catch((error) => {
                    status.warn('⚠️', 'Failed to produce exception event for symbolification', {
                        team_id: event.team_id,
                        uuid: event.uuid,
                        error,
                    })
                    throw error
                })
        )
    }

    private produceEventToKafka(event: RawKafkaEvent) {
        this.promises.push(
            this.hub.kafkaProducer
                .produce({
                    topic: this.hub.CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC,
                    key: event.uuid,
                    value: Buffer.from(JSON.stringify(event)),
                    waitForAck: true,
                })
                .catch(async (error) => {
                    // Some messages end up significantly larger than the original
                    // after plugin processing, person & group enrichment, etc.
                    if (error instanceof MessageSizeTooLarge) {
                        await captureIngestionWarning(this.hub.kafkaProducer, event.team_id, 'message_size_too_large', {
                            eventUuid: event.uuid,
                            distinctId: event.distinct_id,
                        })
                    } else {
                        throw error
                    }
                })
        )
    }

    // private async handleError(err: any, currentStepName: string, currentArgs: any, teamId: number, sentToDql: boolean) {
    //     Sentry.captureException(err, {
    //         tags: { team_id: teamId, pipeline_step: currentStepName },
    //         extra: { currentArgs, originalEvent: this.originalEvent },
    //     })

    //     pipelineStepErrorCounter.labels(currentStepName).inc()

    //     // Should we throw or should we drop and send the event to DLQ.
    //     if (this.shouldRetry(err)) {
    //         pipelineStepThrowCounter.labels(currentStepName).inc()
    //         throw err
    //     }

    //     if (sentToDql) {
    //         pipelineStepDLQCounter.labels(currentStepName).inc()
    //         try {
    //             const message = generateEventDeadLetterQueueMessage(
    //                 this.originalEvent,
    //                 err,
    //                 teamId,
    //                 `plugin_server_ingest_event:${currentStepName}`
    //             )
    //             await this.hub.db.kafkaProducer!.queueMessage({ kafkaMessage: message, waitForAck: true })
    //         } catch (dlqError) {
    //             status.info('🔔', `Errored trying to add event to dead letter queue. Error: ${dlqError}`)
    //             Sentry.captureException(dlqError, {
    //                 tags: { team_id: teamId },
    //                 extra: { currentStepName, currentArgs, originalEvent: this.originalEvent, err },
    //             })
    //         }
    //     }

    //     // These errors are dropped rather than retried
    //     throw new StepErrorNoRetry(currentStepName, currentArgs, err.message)
    // }
}
