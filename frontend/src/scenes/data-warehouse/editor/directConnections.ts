import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import type { TeamPublicType, TeamType } from '~/types'

export const DUCKLAKE_CONNECTION_ID = 'ducklake://default'
export const POSTHOG_WAREHOUSE = '__posthog_warehouse__'
export const LOADING_CONNECTIONS = '__loading_connections__'
export const ADD_POSTGRES_DIRECT_CONNECTION = '__add_postgres_direct_connection__'
export const CONFIGURE_SOURCES = '__configure_sources__'

export function isDuckLakeConnectionId(connectionId?: string | null): boolean {
    return connectionId === DUCKLAKE_CONNECTION_ID
}

export function isDirectQueryEnabled(featureFlags: FeatureFlagsSet): boolean {
    return !!featureFlags[FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY]
}

export function isDuckgresEnabled(currentTeam: TeamType | TeamPublicType | null): boolean {
    return !!currentTeam?.has_ducklake
}

export function shouldShowConnectionSelector(
    featureFlags: FeatureFlagsSet,
    currentTeam: TeamType | TeamPublicType | null
): boolean {
    return isDirectQueryEnabled(featureFlags) || isDuckgresEnabled(currentTeam)
}
