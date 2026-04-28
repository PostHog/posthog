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

/**
 * Mirror the SQL extraction `replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(properties, key), ''), 'null'), '^"|"$', '')`
 * on a parsed JS value, so the live-ingest column write produces byte-identical output to the
 * historical-backfill mutation and to HogQL's JSON fallback (which uses the same SQL).
 *
 * Plugin-server gets the parsed JS value, not the raw JSON text — so we re-encode and apply
 * the SQL nullIf+regex rules. Without this step `String({a:1})` writes `[object Object]` while
 * the SQL backfill writes `{"a":1}`, and the same row reads differently before vs after backfill.
 *
 * The shared fixture at posthog/temporal/backfill_materialized_property/coercion_fixtures.json
 * pins down the cases this function MUST agree with the SQL on.
 */
export function jsonExtractRawAndTrimQuotes(value: unknown): string | null {
    if (value === null || value === undefined) {
        // Mirrors `nullIf(extract, 'null')`: a JSON `null` becomes SQL NULL.
        return null
    }
    const json = JSON.stringify(value)
    // `JSON.stringify(undefined)` returns `undefined` — handled above. For all other inputs
    // it returns a string, never the empty string, so the SQL `nullIf(extract, '')` branch is
    // unreachable from real ingestion input.
    if (json === 'null') {
        // JSON.stringify(null) === 'null' but we already returned for that. This is for any
        // future edge case where the encoder produces the literal 'null' string; keep parity
        // with SQL's nullIf(..., 'null').
        return null
    }
    // Strip exactly one leading and one trailing `"` if both present (mirrors `^"|"$`).
    if (json.length >= 2 && json[0] === '"' && json[json.length - 1] === '"') {
        return json.slice(1, -1)
    }
    return json
}

/**
 * Best-effort parse of a datetime string into a Luxon DateTime. Tries the formats
 * ClickHouse's `parseDateTime64BestEffortOrNull` accepts most reliably:
 *   - ISO 8601 (with or without `T` and timezone)
 *   - SQL format `YYYY-MM-DD HH:mm:ss`
 *   - date-only `YYYY-MM-DD`
 *   - RFC 2822
 *
 * Out-of-spec formats (e.g. `MM/DD/YYYY`) may still parse on the SQL side; this function
 * returns null for them. The shared fixture documents which formats are guaranteed to round-trip.
 */
function tryParseDateTime(text: string): DateTime | null {
    const isoT = DateTime.fromISO(text, { zone: 'utc' })
    if (isoT.isValid) {
        return isoT
    }
    const sqlForm = DateTime.fromFormat(text, 'yyyy-MM-dd HH:mm:ss', { zone: 'utc' })
    if (sqlForm.isValid) {
        return sqlForm
    }
    const rfc = DateTime.fromRFC2822(text, { zone: 'utc' })
    if (rfc.isValid) {
        return rfc
    }
    return null
}

function convertPropertyValueForSlot(
    value: unknown,
    propertyType: MaterializedColumnSlot['property_type']
): string | number | null {
    // First reproduce the SQL extraction so the input to the type cast matches what the
    // backfill mutation sees. After this the cases below differ only in the type wrapper
    // (toFloat64OrNull / transform / parseDateTime64BestEffortOrNull) — match each precisely.
    const raw = jsonExtractRawAndTrimQuotes(value)
    if (raw === null) {
        return null
    }
    switch (propertyType) {
        case 'String':
            return raw
        case 'Numeric': {
            // Match `toFloat64OrNull(raw)`. parseFloat tolerates leading whitespace; SQL
            // tolerates leading and trailing. Both reject non-numeric input by returning NULL.
            const numValue = parseFloat(raw)
            return isNaN(numValue) ? null : numValue
        }
        case 'Boolean':
            // Match `transform(toString(raw), ['true', 'false'], [1, 0], NULL)` — case-sensitive
            // lowercase only. '1', '0', 'TRUE', 'True', 'yes', etc. all return NULL.
            if (raw === 'true') {
                return 1
            }
            if (raw === 'false') {
                return 0
            }
            return null
        case 'DateTime': {
            const parsed = tryParseDateTime(raw)
            if (parsed === null) {
                return null
            }
            // dmat datetime columns are Nullable(DateTime64(6, 'UTC')) — pad to 6 decimal
            // places so the string we write to Kafka matches the format ClickHouse uses when
            // reading the column back, which lets HogQL queries that compare a JSON-fallback
            // datetime to a dmat datetime return TRUE for the same instant. castTimestampToClickhouseFormat
            // emits millisecond precision (3 decimals); pad to microsecond precision (6).
            const millis = castTimestampToClickhouseFormat(parsed, TimestampFormat.ClickHouse)
            const dot = millis.lastIndexOf('.')
            if (dot === -1) {
                return `${millis}.000000`
            }
            return millis + '0'.repeat(6 - (millis.length - dot - 1))
        }
    }
}
