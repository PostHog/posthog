/**
 * Resolves a condition set's effective aggregation group type index, mirroring the backend's
 * `effective_aggregation` (rust/feature-flags/src/flags/flag_property_group.rs). The per-condition
 * field has three states that must stay distinct — `??` would wrongly collapse the first two:
 * - `undefined` — not set, inherit the flag-level (global) index
 * - `null` — explicitly target users, overriding the global group index
 * - number — explicitly target that group type
 */
export function resolveAggregationGroupTypeIndex(
    conditionGroupTypeIndex: number | null | undefined,
    flagLevelGroupTypeIndex: number | null | undefined
): number | null {
    return (conditionGroupTypeIndex !== undefined ? conditionGroupTypeIndex : flagLevelGroupTypeIndex) ?? null
}
