import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { Properties } from '~/plugin-scaffold'

import {
    Element,
    MaterializedColumnSlot,
    Person,
    PersonMode,
    PreIngestionEvent,
    ProcessedEvent,
    TimestampFormat,
} from '../../types'
import { elementsToString, extractElements } from '../../utils/elements-chain'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { castTimestampToClickhouseFormat } from '../../utils/utils'
import { MAX_GROUP_TYPES_PER_TEAM } from './group-type-manager'
import { uuidFromDistinctId } from './person-uuid'

/** Maps PropertyType (Django enum) → the suffix used in dmat column names. */
const PROPERTY_TYPE_TO_COLUMN_SUFFIX: Record<MaterializedColumnSlot['property_type'], string> = {
    String: 'string',
    Numeric: 'numeric',
    Boolean: 'bool',
    DateTime: 'datetime',
}

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
    person: Person | undefined,
    processPerson: boolean,
    historicalMigration: boolean,
    capturedAt: Date | null,
    materializedColumnSlots: MaterializedColumnSlot[] = []
): ProcessedEvent {
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

    let eventPersonProperties: Record<string, unknown> = {}
    if (processPerson && person) {
        eventPersonProperties = {
            ...person.properties,
            // For consistency, we'd like events to contain the properties that they set, even if those were changed
            // before the event is ingested.
            ...(properties.$set || {}),
        }
    } else if (!processPerson) {
        // TODO: Move this into `normalizeEventStep` where it belongs, but the code structure
        // and tests demand this for now.
        for (let groupTypeIndex = 0; groupTypeIndex < MAX_GROUP_TYPES_PER_TEAM; ++groupTypeIndex) {
            const key = `$group_${groupTypeIndex}`
            delete properties[key]
        }
    }

    let personMode: PersonMode = 'full'
    if (person?.force_upgrade) {
        personMode = 'force_upgrade'
    } else if (!processPerson) {
        personMode = 'propertyless'
    }

    // Use person UUID if available, otherwise generate deterministic UUID from distinct_id
    const personId = person?.uuid ?? uuidFromDistinctId(teamId, distinctId)

    const processedEvent: ProcessedEvent = {
        uuid,
        event,
        properties: properties ?? {},
        timestamp,
        team_id: teamId,
        project_id: projectId,
        distinct_id: distinctId,
        elements_chain: elementsChain,
        created_at: null,
        captured_at: capturedAt,
        person_id: personId,
        person_properties: eventPersonProperties,
        person_created_at: person?.created_at ?? null,
        person_mode: personMode,
        // Only include historical_migration when true to avoid bloating messages
        ...(historicalMigration ? { historical_migration: true } : {}),
    }

    if (materializedColumnSlots.length > 0) {
        const dmatColumns = extractDynamicMaterializedColumns(properties ?? {}, materializedColumnSlots)
        if (Object.keys(dmatColumns).length > 0) {
            processedEvent.dmat_columns = dmatColumns
        }
    }

    return processedEvent
}

/**
 * Compute dmat column values for one event from the team's slot configuration.
 *
 * Returns a flat map of `dmat_<type>_<index>` → coerced value. Only properties present on
 * the event are included; missing properties are left unset so ClickHouse stores NULL,
 * which lets HogQL fall back to JSON extraction for events that pre-date the slot.
 *
 * Coercion mirrors the SQL extraction in
 * `posthog/temporal/backfill_materialized_property/activities.py::_generate_property_extraction_sql`
 * so that historical (backfilled) and live (ingested-here) values are byte-for-byte identical.
 */
function extractDynamicMaterializedColumns(
    properties: Properties,
    slots: MaterializedColumnSlot[]
): Record<string, string | number | null> {
    const out: Record<string, string | number | null> = {}

    for (const slot of slots) {
        const propertyValue = properties[slot.property_name]
        if (propertyValue === undefined || propertyValue === null) {
            continue
        }

        const converted = convertPropertyValueForSlot(propertyValue, slot.property_type)
        if (converted === null) {
            continue
        }

        const suffix = PROPERTY_TYPE_TO_COLUMN_SUFFIX[slot.property_type]
        out[`dmat_${suffix}_${slot.slot_index}`] = converted

        // Dual-write during compaction: the slot is being repacked, so write the same value to
        // the future column too. HogQL still reads from `slot_index` until the workflow swaps
        // them post-mutation; once swapped, future events land directly on the new column and
        // the old column becomes orphaned (still has data, but no slot points to it).
        if (slot.compaction_target_slot_index !== null) {
            out[`dmat_${suffix}_${slot.compaction_target_slot_index}`] = converted
        }
    }

    return out
}

function convertPropertyValueForSlot(
    value: unknown,
    propertyType: MaterializedColumnSlot['property_type']
): string | number | null {
    try {
        switch (propertyType) {
            case 'String':
                return String(value)
            case 'Numeric': {
                const numValue = parseFloat(String(value))
                return isNaN(numValue) ? null : numValue
            }
            case 'Boolean': {
                const strValue = String(value).toLowerCase()
                if (strValue === 'true' || strValue === '1') {
                    return 1
                }
                if (strValue === 'false' || strValue === '0') {
                    return 0
                }
                return null
            }
            case 'DateTime': {
                // Match HogQL's parseDateTime64BestEffortOrNull behavior: parse loosely; reject if not parseable.
                const parsed = DateTime.fromISO(String(value), { zone: 'utc' })
                if (!parsed.isValid) {
                    return null
                }
                return castTimestampToClickhouseFormat(parsed, TimestampFormat.ClickHouse)
            }
            default:
                return null
        }
    } catch {
        return null
    }
}
