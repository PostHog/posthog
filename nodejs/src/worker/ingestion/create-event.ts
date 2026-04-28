import { Counter } from 'prom-client'

import { Properties } from '~/plugin-scaffold'

import { Element, MaterializedColumnSlot, Person, PersonMode, PreIngestionEvent, ProcessedEvent } from '../../types'
import { elementsToString, extractElements } from '../../utils/elements-chain'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { MAX_GROUP_TYPES_PER_TEAM } from './group-type-manager'
import { uuidFromDistinctId } from './person-uuid'

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
 * Returns a flat map of `dmat_string_<index>` → string. Only properties present on the event
 * are included; missing properties are left unset so ClickHouse stores NULL, which lets HogQL
 * fall back to JSON extraction for events that pre-date the slot.
 *
 * All dmat columns are `Nullable(String)`; HogQL casts at read time using the same wrapper
 * it applies to normal `mat_*` columns (toFloat / toBool / parseDateTime64BestEffortOrNull).
 * The string we write here MUST be byte-identical to what
 * `_generate_property_extraction_sql` produces against the same property — that's the contract
 * the parity fixture pins.
 */
function extractDynamicMaterializedColumns(
    properties: Properties,
    slots: MaterializedColumnSlot[]
): Record<string, string> {
    const out: Record<string, string> = {}

    for (const slot of slots) {
        const propertyValue = properties[slot.property_name]
        if (propertyValue === undefined || propertyValue === null) {
            continue
        }

        const raw = jsonExtractRawAndTrimQuotes(propertyValue)
        if (raw === null) {
            continue
        }

        out[`dmat_string_${slot.slot_index}`] = raw

        // Dual-write during compaction: the slot is being repacked, so write the same value to
        // the future column too. HogQL still reads from `slot_index` until the workflow swaps
        // them post-mutation; once swapped, future events land directly on the new column and
        // the old column becomes orphaned (still has data, but no slot points to it).
        if (slot.compaction_target_slot_index !== null) {
            out[`dmat_string_${slot.compaction_target_slot_index}`] = raw
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
