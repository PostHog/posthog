import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { Properties } from '@posthog/plugin-scaffold'

import { Element, Person, PersonMode, PreIngestionEvent, RawKafkaEvent, Team, TimestampFormat } from '../../types'
import { safeClickhouseString } from '../../utils/db/utils'
import { elementsToString, extractElements } from '../../utils/elements-chain'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { castTimestampOrNow, castTimestampToClickhouseFormat } from '../../utils/utils'
import { MAX_GROUP_TYPES_PER_TEAM } from './group-type-manager'

const elementsOrElementsChainCounter = new Counter({
    name: 'events_pipeline_elements_or_elements_chain_total',
    help: 'Number of times elements or elements_chain appears on event',
    labelNames: ['type'],
})

export function getElementsChain(properties: Properties): string {
    /*
    We're deprecating $elements in favor of $elements_chain, which doesn't require extra
    processing on the ingestion side and is the way we store elements in ClickHouse.
    As part of that we'll move posthog-js to send us $elements_chain as string directly,
    but we still need to support the old way of sending $elements and converting them
    to $elements_chain, while everyone hasn't upgraded.
    */
    let elementsChain = ''
    if (properties['$elements_chain']) {
        elementsChain = properties['$elements_chain']
        elementsOrElementsChainCounter.labels('elements_chain').inc()
    } else if (properties['$elements']) {
        const elements: Record<string, any>[] | undefined = properties['$elements']
        let elementsList: Element[] = []
        if (elements && elements.length) {
            elementsList = extractElements(elements)
            elementsChain = elementsToString(elementsList)
        }
        elementsOrElementsChainCounter.labels('elements').inc()
    }
    delete properties['$elements_chain']
    delete properties['$elements']
    return elementsChain
}

export function createEvent(
    preIngestionEvent: PreIngestionEvent,
    person: Person,
    processPerson: boolean,
    historicalMigration: boolean,
    capturedAt: Date | null,
    team?: Team | null
): RawKafkaEvent {
    const { eventUuid: uuid, event, teamId, projectId, distinctId, properties, timestamp } = preIngestionEvent

    let elementsChain = ''
    try {
        elementsChain = getElementsChain(properties)
    } catch (error) {
        captureException(error, { tags: { team_id: teamId } })
        logger.warn('⚠️', 'Failed to process elements', {
            uuid,
            teamId: teamId,
            properties,
            error,
        })
    }

    let eventPersonProperties = '{}'
    if (processPerson) {
        eventPersonProperties = JSON.stringify({
            ...person.properties,
            // For consistency, we'd like events to contain the properties that they set, even if those were changed
            // before the event is ingested.
            ...(properties.$set || {}),
        })
    } else {
        // TODO: Move this into `normalizeEventStep` where it belongs, but the code structure
        // and tests demand this for now.
        for (let groupTypeIndex = 0; groupTypeIndex < MAX_GROUP_TYPES_PER_TEAM; ++groupTypeIndex) {
            const key = `$group_${groupTypeIndex}`
            delete properties[key]
        }
    }

    let personMode: PersonMode = 'full'
    if (person.force_upgrade) {
        personMode = 'force_upgrade'
    } else if (!processPerson) {
        personMode = 'propertyless'
    }

    const rawEvent: RawKafkaEvent = {
        uuid,
        event: safeClickhouseString(event),
        properties: JSON.stringify(properties ?? {}),
        timestamp: castTimestampOrNow(timestamp, TimestampFormat.ClickHouse),
        team_id: teamId,
        project_id: projectId,
        distinct_id: safeClickhouseString(distinctId),
        elements_chain: safeClickhouseString(elementsChain),
        created_at: castTimestampOrNow(null, TimestampFormat.ClickHouse),
        captured_at:
            capturedAt !== null
                ? castTimestampToClickhouseFormat(DateTime.fromJSDate(capturedAt), TimestampFormat.ClickHouse)
                : null,
        person_id: person.uuid,
        person_properties: eventPersonProperties,
        person_created_at: castTimestampOrNow(person.created_at, TimestampFormat.ClickHouseSecondPrecision),
        person_mode: personMode,
        // Only include historical_migration when true to avoid bloating messages
        ...(historicalMigration ? { historical_migration: true } : {}),
    }

    if (team) {
        extractDynamicMaterializedColumns(rawEvent, properties, team)
    }

    return rawEvent
}

function extractDynamicMaterializedColumns(rawEvent: RawKafkaEvent, properties: Properties, team: Team): void {
    if (!team.materialized_column_slots || team.materialized_column_slots.length === 0) {
        return
    }

    for (const slot of team.materialized_column_slots) {
        // Only process READY and BACKFILL slots (skip ERROR)
        if (slot.state !== 'READY' && slot.state !== 'BACKFILL') {
            continue
        }

        const propertyValue = properties[slot.property_name]
        if (propertyValue === undefined || propertyValue === null) {
            continue
        }

        const columnName = `dmat_${slot.slot_property_type}_${slot.slot_index}` as keyof RawKafkaEvent
        const convertedValue = convertPropertyValue(propertyValue, slot.slot_property_type)

        if (convertedValue !== null) {
            ;(rawEvent as any)[columnName] = convertedValue
        }
    }
}

function convertPropertyValue(
    value: any,
    propertyType: 'string' | 'numeric' | 'bool' | 'datetime'
): string | number | null {
    try {
        switch (propertyType) {
            case 'string':
                return String(value)
            case 'numeric':
                const numValue = parseFloat(value)
                return isNaN(numValue) ? null : numValue
            case 'bool':
                const strValue = String(value).toLowerCase()
                if (strValue === 'true' || strValue === '1') {
                    return 1
                }
                if (strValue === 'false' || strValue === '0') {
                    return 0
                }
                return null
            case 'datetime':
                return value
            default:
                return null
        }
    } catch {
        return null
    }
}
