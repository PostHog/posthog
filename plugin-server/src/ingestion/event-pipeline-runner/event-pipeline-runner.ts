import { PluginEvent } from '@posthog/plugin-scaffold'
import { captureException } from '@sentry/node'
import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { KAFKA_INGESTION_WARNINGS } from '../../config/kafka-topics'
import { TopicMessage } from '../../kafka/producer'
import { eventDroppedCounter } from '../../main/ingestion-queues/metrics'
import { runInstrumentedFunction } from '../../main/utils'
import { Hub, Person, PersonMode, PipelineEvent, RawKafkaEvent, Team, TimestampFormat } from '../../types'
import { MessageSizeTooLarge } from '../../utils/db/error'
import { safeClickhouseString, sanitizeEventName, sanitizeString } from '../../utils/db/utils'
import { normalizeEvent, normalizeProcessPerson } from '../../utils/event'
import { logger } from '../../utils/logger'
import { castTimestampOrNow, UUID } from '../../utils/utils'
import { MAX_GROUP_TYPES_PER_TEAM } from '../../worker/ingestion/group-type-manager'
import { PersonState } from '../../worker/ingestion/person-state'
import { uuidFromDistinctId } from '../../worker/ingestion/person-uuid'
import { upsertGroup } from '../../worker/ingestion/properties-updater'
import { parseEventTimestamp } from '../../worker/ingestion/timestamps'
import { captureIngestionWarning } from '../../worker/ingestion/utils'
import { runProcessEvent } from '../../worker/plugins/run'
import { processAiEvent } from '../ai-costs/process-ai-event'
import { getElementsChain } from './utils/event-utils'
import { extractHeatmapData } from './utils/heatmaps'

export type TopicMessageWithErrorHandler = TopicMessage & {
    errorHandler?: (error: Error) => void
}

export class EventDroppedError extends Error {
    public doNotSendToDLQ: boolean = false
    public ingestionWarningDetails?: Record<string, any>
    public isRetriable: boolean = false

    constructor(
        public ingestionWarning: string,
        options?: {
            doNotSendToDLQ?: boolean
            message?: string
            ingestionWarningDetails?: Record<string, any>
        }
    ) {
        super(options?.message ?? ingestionWarning)
        this.doNotSendToDLQ = options?.doNotSendToDLQ ?? false
        this.ingestionWarningDetails = options?.ingestionWarningDetails
    }
}

export const droppedEventFromTransformationsCounter = new Counter({
    name: 'event_pipeline_transform_dropped_events_total',
    help: 'Count of events dropped by transformations',
})

export class EventPipelineRunnerV2 {
    private team?: Team
    private event: PluginEvent
    private shouldProcessPerson: boolean = true
    private timestamp?: DateTime
    private person?: Person
    private promises: Promise<any>[] = []

    constructor(
        private hub: Hub,
        private originalEvent: PipelineEvent,
        private hogTransformer: HogTransformerService,
        private comparisonMode: boolean = false
    ) {
        this.comparisonMode = comparisonMode
        this.event = {
            ...this.originalEvent,
            properties: {
                ...(this.originalEvent.properties ?? {}),
            },
            team_id: originalEvent.team_id ?? -1,
        }
    }

    public getPromises(): Promise<any>[] {
        return this.promises
    }

    private captureIngestionWarning(warning: string, _details: Record<string, any> = {}): void {
        if (this.comparisonMode) {
            return
        }

        // NOTE: There is a shared util for this but it is only used by ingestion so keeping it here now
        const details = {
            eventUuid: typeof this.event.uuid !== 'string' ? JSON.stringify(this.event.uuid) : this.event.uuid,
            event: this.event.event,
            distinctId: this.event.distinct_id,
            ..._details,
        }

        this.promises.push(
            this.hub.kafkaProducer.queueMessages({
                topic: KAFKA_INGESTION_WARNINGS,
                messages: [
                    {
                        value: JSON.stringify({
                            team_id: this.team?.id,
                            type: warning,
                            source: 'plugin-server',
                            details: JSON.stringify(details),
                            timestamp: castTimestampOrNow(null, TimestampFormat.ClickHouse),
                        }),
                    },
                ],
            })
        )
    }

    private dropEvent(dropCause: string): undefined {
        if (this.comparisonMode) {
            return
        }
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: dropCause,
            })
            .inc()
    }

    async run(): Promise<RawKafkaEvent | undefined> {
        try {
            return await this._run()
        } catch (error) {
            // We capture ingestion warnings but allow the parent to decide on DLQ, retries etc.
            if (error instanceof EventDroppedError) {
                this.captureIngestionWarning(error.ingestionWarning, error.ingestionWarningDetails)
            }

            throw error
        }
    }

    private async _run(): Promise<RawKafkaEvent | undefined> {
        // First of all lets get the team
        this.team = (await this.getTeam()) ?? undefined

        if (!this.team) {
            return this.dropEvent('invalid_token')
        }
        this.event.team_id = this.team.id

        // Early exit for client ingestion warnings
        if (this.event.event === '$$client_ingestion_warning') {
            this.captureIngestionWarning('client_ingestion_warning', {
                message: this.event.properties?.$$client_ingestion_warning_message,
            })
            return
        }

        this.validateUuid()
        this.validatePersonProcessing()

        // This is where we cut off for heatmaps...

        if (this.event.event === '$$heatmap') {
            // Heatmaps are not typical events so we bypass alot of the usual processing
            this.normalizeEvent()
            this.processHeatmaps()
            return
        }

        // TODO: This needs better testing
        const postCookielessEvent = await this.hub.cookielessManager.processEvent(this.event)
        if (postCookielessEvent == null) {
            droppedEventFromTransformationsCounter.inc()
            // NOTE: In this case we just return as it is expected, not an ingestion error
            return
        }

        const pluginProcessed = await this.processPlugins()
        if (!pluginProcessed) {
            droppedEventFromTransformationsCounter.inc()
            // NOTE: In this case we just return as it is expected, not an ingestion error
            return
        }

        const result = await this.hogTransformer.transformEventAndProduceMessages(this.event, {
            skipProduce: this.comparisonMode,
        })

        if (!result.event) {
            droppedEventFromTransformationsCounter.inc()
            return
        }

        this.processAiEvent()
        this.normalizeEvent()
        await this.processPerson()
        await this.processGroups()

        this.trackFirstEventIngestion()
        this.processHeatmaps()

        const kafkaEvent = this.createKafkaEvent()

        if (this.event.event === '$exception' && !this.event.properties?.hasOwnProperty('$sentry_event_id')) {
            this.produceExceptionSymbolificationEventStep(kafkaEvent)
            return
        }

        this.produceEventToKafka(kafkaEvent)

        return kafkaEvent
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
            throw new EventDroppedError('invalid_event_uuid', {
                message: `Not a valid UUID: "${this.event.uuid}"`,
            })
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

        const skipPersonsProcessingForDistinctIds = this.hub.eventsToSkipPersonsProcessingByToken.get(
            this.originalEvent.token!
        )

        if (skipPersonsProcessingForDistinctIds?.includes(this.event.distinct_id)) {
            this.event.properties!.$process_person_profile = false
        }

        const processPersonProfile = this.event.properties!.$process_person_profile

        if (processPersonProfile === false) {
            if (['$identify', '$create_alias', '$merge_dangerously', '$groupidentify'].includes(this.event.event)) {
                throw new EventDroppedError('invalid_event_when_process_person_profile_is_false', {
                    message: `Invalid event when process_person_profile is false: "${this.event.event}"`,
                    // In this case we don't need to store it in the DLQ as this is expected behavior
                    doNotSendToDLQ: true,
                })
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

    private async processPlugins(): Promise<boolean> {
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
        this.event.event = sanitizeEventName(this.event.event)
        this.event = normalizeEvent(this.event)
        this.event = normalizeProcessPerson(this.event, this.shouldProcessPerson)
        this.timestamp = parseEventTimestamp(this.event)
    }

    private processAiEvent() {
        if (this.event.event === '$ai_generation' || this.event.event === '$ai_embedding') {
            try {
                this.event = processAiEvent(this.event)
            } catch (error) {
                // NOTE: Whilst this is pre-production we want to make it as optional as possible
                // so we don't block the pipeline if it fails
                captureException(error)
                logger.error(error)
            }
        }
    }

    private trackFirstEventIngestion() {
        // We always track 1st event ingestion
        if (this.comparisonMode) {
            return
        }

        // TODO: In the future we should do this a level up at the batch level. We just need higher level team loading
        // TODO: Move this up a level to run _after_ we have processed the event and resolved the team
        // this.promises.push(this.hub.teamManager.setTeamIngestedEvent(this.team!, this.event.properties!))
    }

    private async processPerson() {
        if (this.comparisonMode) {
            // TRICKY: We don't want to refactor PersonState yet to be write optional so we need to just skip it
            const fakePerson: Person = {
                team_id: this.team!.id,
                properties: {},
                uuid: uuidFromDistinctId(this.team!.id, this.event.distinct_id),
                created_at: this.timestamp!,
            }
            this.person = fakePerson
            return
        }

        // NOTE: PersonState could derive so much of this stuff instead of it all being passed in
        const [person, kafkaAck] = await new PersonState(
            this.event,
            this.team!,
            String(this.event.distinct_id),
            this.timestamp!,
            this.shouldProcessPerson,
            this.hub.db
        ).update()

        this.person = person
        // NOTE: In the future we should return the kafka messages rather than pushing them within the PersonState
        this.promises.push(kafkaAck)
    }

    private async processGroups() {
        if (!this.shouldProcessPerson) {
            return
        }

        // Adds group_0 etc values to properties
        for (const [groupType, groupIdentifier] of Object.entries(this.event.properties!.$groups || {})) {
            const columnIndex = await this.hub.groupTypeManager.fetchGroupTypeIndex(
                this.team!.id,
                this.team!.project_id,
                groupType
            )
            if (columnIndex !== null) {
                // :TODO: Update event column instead
                this.event.properties![`$group_${columnIndex}`] = groupIdentifier
            }
        }

        if (this.event.event === '$groupidentify' && !this.comparisonMode) {
            if (!this.event.properties!['$group_type'] || !this.event.properties!['$group_key']) {
                return
            }

            const {
                $group_type: groupType,
                $group_key: groupKey,
                $group_set: groupPropertiesToSet,
            } = this.event.properties!
            const groupTypeIndex = await this.hub.groupTypeManager.fetchGroupTypeIndex(
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

    private processHeatmaps() {
        try {
            if (this.team?.heatmaps_opt_in !== false) {
                const heatmapEvents = extractHeatmapData(this.event) ?? []

                this.promises.push(
                    this.hub.kafkaProducer.queueMessages({
                        topic: this.hub.CLICKHOUSE_HEATMAPS_KAFKA_TOPIC,
                        messages: heatmapEvents.map((rawEvent) => ({
                            key: this.event.uuid,
                            value: Buffer.from(JSON.stringify(rawEvent)),
                        })),
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
            captureException(error, { tags: { team_id: this.team!.id } })
            logger.warn('⚠️', 'Failed to process elements', {
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
            this.hub.kafkaProducer.queueMessages({
                topic: this.hub.EXCEPTIONS_SYMBOLIFICATION_KAFKA_TOPIC,
                messages: [
                    {
                        key: event.uuid,
                        value: Buffer.from(JSON.stringify(event)),
                    },
                ],
            })
        )
    }

    private produceEventToKafka(event: RawKafkaEvent) {
        if (this.comparisonMode) {
            return
        }
        this.promises.push(
            this.hub.kafkaProducer
                .produce({
                    topic: this.hub.CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC,
                    value: Buffer.from(JSON.stringify(event)),
                    key: event.uuid,
                    headers: [
                        {
                            key: 'team_id',
                            value: this.team!.id.toString(),
                        },
                    ],
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
}
