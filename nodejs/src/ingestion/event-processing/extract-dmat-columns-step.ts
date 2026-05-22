import { MaterializedColumnSlot } from '../../types'
import { MaterializedColumnSlotManager } from '../../utils/materialized-column-slot-manager'
import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'
import { CreateEventStepResult } from './create-event-step'

/**
 * Writes the team's configured dmat (`dmat_string_<index>`) columns onto each event built by
 * `createCreateEventStep`. Kept as its own step (rather than folded into create-event) so the
 * dmat feature is self-contained and only attached to pipelines that want it.
 *
 * The feature flag (`INGESTION_DMAT_COLUMN_WRITES_ENABLED`) is enforced inside
 * `MaterializedColumnSlotManager`: when disabled, `getSlots` returns `[]`, so this step no-ops.
 */
export function createExtractDmatColumnsStep<O extends string, T extends CreateEventStepResult<O>>(
    materializedColumnSlotManager: Pick<MaterializedColumnSlotManager, 'getSlots'>
): ProcessingStep<T, T> {
    return async function extractDmatColumnsStep(input) {
        // A slot-config load failure propagates out of getSlots (fails the event closed) rather
        // than returning []: once a slot is READY, HogQL reads the column with no JSON fallback,
        // so emitting an event without its dmat column would corrupt that team's reads.
        const slots = await materializedColumnSlotManager.getSlots(input.teamId)
        if (slots.length === 0) {
            // No slots configured for this team, or the feature is disabled. Nothing to write.
            return ok(input)
        }

        for (const { event } of input.eventsToEmit) {
            const dmatColumns = extractDynamicMaterializedColumns(event.properties, slots)
            if (Object.keys(dmatColumns).length > 0) {
                event.dmat_columns = dmatColumns
            }
        }

        return ok(input)
    }
}

/**
 * Missing properties are left unset → ClickHouse stores NULL → HogQL falls back to JSON for
 * events that pre-date the slot. All dmat columns are `Nullable(String)`; HogQL casts at read.
 *
 * The string MUST be byte-identical to `_generate_property_extraction_sql`. Parity is pinned
 * by `posthog/temporal/backfill_materialized_property/coercion_fixtures.json`.
 */
export function extractDynamicMaterializedColumns(
    properties: Record<string, unknown>,
    slots: MaterializedColumnSlot[]
): Record<string, string> {
    const out: Record<string, string> = {}

    for (const slot of slots) {
        // Only own enumerable properties — a slot configured for an inherited name like
        // `constructor` must not pick up `Object.prototype.constructor` (a function), which
        // would otherwise be passed to `jsonExtractRawAndTrimQuotes`.
        if (!Object.prototype.hasOwnProperty.call(properties, slot.property_name)) {
            continue
        }

        const propertyValue = properties[slot.property_name]
        if (propertyValue === undefined || propertyValue === null) {
            continue
        }

        const raw = jsonExtractRawAndTrimQuotes(propertyValue)
        if (raw === null) {
            continue
        }

        out[`dmat_string_${slot.slot_index}`] = raw
    }

    return out
}

/**
 * Mirrors SQL `replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(properties, key), ''), 'null'), '^"|"$', '')`
 * on a parsed JS value. Plugin-server gets parsed values, not raw JSON text — without this
 * `String({a:1})` would write `[object Object]` while the SQL backfill writes `{"a":1}`, and
 * the same row would read differently before vs after backfill.
 */
export function jsonExtractRawAndTrimQuotes(value: unknown): string | null {
    if (value === null || value === undefined) {
        return null
    }
    const json = JSON.stringify(value)
    if (json === 'null') {
        return null
    }
    // Mirrors SQL `^"|"$`: strip one leading and one trailing `"` if both present.
    if (json.length >= 2 && json[0] === '"' && json[json.length - 1] === '"') {
        return json.slice(1, -1)
    }
    return json
}
