import { FeatureFlagConfig, FeatureFlagFilters, FeatureFlagRulesV2Config } from '~/types'

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
