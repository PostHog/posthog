import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { FeatureFlagConfig, FeatureFlagFilters, FeatureFlagRulesV2Config, TeamPublicType, TeamType } from '~/types'

export type FeatureFlagConfigFormat = 'v1' | 'v2' | 'unsupported'

/** Mirrors the server's detector: no `version` or `1` is v1, `2` is v2, anything else is unsupported here. */
export function featureFlagConfigFormat(filters: FeatureFlagConfig | null | undefined): FeatureFlagConfigFormat {
    const version = filters?.version
    if (version === undefined || version === 1) {
        return 'v1'
    }
    if (version === 2) {
        return 'v2'
    }
    return 'unsupported'
}

export function isV1FeatureFlagConfig(filters: FeatureFlagConfig | null | undefined): filters is FeatureFlagFilters {
    return featureFlagConfigFormat(filters) === 'v1'
}

export function isRulesV2FeatureFlagConfig(
    filters: FeatureFlagConfig | null | undefined
): filters is FeatureFlagRulesV2Config {
    return featureFlagConfigFormat(filters) === 'v2'
}

export function featureFlagConfigFormatLabel(filters: FeatureFlagConfig | null | undefined): string {
    const version = filters?.version
    return featureFlagConfigFormat(filters) === 'v2' ? 'Rules v2' : `Config v${String(version)} (unsupported)`
}

/** The rules v2 create contract rejects `evaluation_contexts`, so a project that requires them rejects every rules v2 create. */
export function rulesV2CreateDisabledReason(
    team: TeamPublicType | TeamType | null,
    enabledFeatures: FeatureFlagsSet
): string | null {
    return enabledFeatures[FEATURE_FLAGS.FLAG_EVALUATION_TAGS] && team?.require_evaluation_contexts
        ? "This project requires evaluation contexts on new flags, and rules v2 flags can't set them yet."
        : null
}

/** Whether the rules v2 editor can edit this document: boolean return type, person assignment, no experiment rules. */
export function isRulesV2EditableConfig(filters: FeatureFlagConfig | null | undefined): boolean {
    return (
        isRulesV2FeatureFlagConfig(filters) &&
        filters.return_type === 'boolean' &&
        filters.aggregation_group_type_index == null &&
        filters.rules.every((rule) => rule.rule_type !== 'experiment' && typeof rule.value === 'boolean')
    )
}
