import { isApprovalRequiredError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { FeatureFlagConfig, FeatureFlagFilters, FeatureFlagRulesV2Config } from '~/types'

export type FeatureFlagConfigFormat = 'v1' | 'v2' | 'unsupported'

export const UNSUPPORTED_CONFIG_DISABLED_REASON =
    'This flag is stored in a configuration version this page cannot change.'
export const ARCHIVE_UNAVAILABLE_DISABLED_REASON = 'Archiving is not available for this flag yet.'
export const RESTORE_UNAVAILABLE_DISABLED_REASON = 'Restoring is not available for this flag yet.'

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

/** Every write to a row in another config version must carry the row version; v1 keeps its merge semantics. */
export function rowVersionToken(
    flag: { filters?: FeatureFlagConfig | null; version?: number | null } | null | undefined
): { version?: number } {
    return !flag || isV1FeatureFlagConfig(flag.filters) || flag.version == null ? {} : { version: flag.version }
}

export function isStaleRowVersionError(token: { version?: number }, error: any): boolean {
    return token.version !== undefined && error?.status === 409 && !isApprovalRequiredError(error)
}

// The conflicting write may have replaced the whole document, so a stale row version reloads the flag.
export function reloadIfStaleRowVersion(token: { version?: number }, error: any, reload: () => void): boolean {
    if (!isStaleRowVersionError(token, error)) {
        return false
    }
    lemonToast.error(error?.detail || 'This flag changed elsewhere and has been reloaded.')
    reload()
    return true
}

export function featureFlagConfigFormatLabel(filters: FeatureFlagConfig | null | undefined): string {
    const version = filters?.version
    return featureFlagConfigFormat(filters) === 'v2' ? 'Rules v2' : `Config v${String(version)} (unsupported)`
}
