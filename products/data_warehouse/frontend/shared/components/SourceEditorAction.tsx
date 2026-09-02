import React from 'react'

import { AccessControlAction, AccessControlActionChildrenProps } from 'lib/components/AccessControlAction'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType, ExternalDataSource, ExternalDataSourceSchema } from '~/types'

/**
 * Compute the editor access-disabled reason for an external data source as plain values.
 *
 * Prefer this over the render-prop form of `SourceEditorAction` when the gated subtree owns
 * `useState` (e.g. `LemonSelect` dropdown open state, `LemonInput` focus, controlled forms):
 * the render-prop passes a fresh inline function to React each parent render, which
 * `AccessControlAction` treats as a new component type and remounts — wiping any local state.
 * Deriving the values once and feeding them into a stable element keeps the fiber identity.
 */
export function useSourceEditorAccess(source: ExternalDataSource | null): {
    disabled: boolean
    disabledReason: string | undefined
} {
    const disabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.ExternalDataSource,
        AccessControlLevel.Editor,
        source?.user_access_level
    )
    return {
        disabled: !!disabledReason,
        disabledReason: disabledReason ?? undefined,
    }
}

/**
 * Per-table variant of {@link useSourceEditorAccess}. `schema.user_access_level` is the effective
 * level for the table (the most restrictive of the source and the synced table), so it covers both
 * the source-level and per-table-locked cases.
 */
export function useSchemaEditorAccess(schema: ExternalDataSourceSchema | null): {
    disabled: boolean
    disabledReason: string | undefined
} {
    const disabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.WarehouseTable,
        AccessControlLevel.Editor,
        schema?.user_access_level
    )
    return {
        disabled: !!disabledReason,
        disabledReason: disabledReason ?? undefined,
    }
}

/**
 * Gates children on Editor access for an external data source — used consistently across schema
 * and source settings UI so that viewers see the control as disabled with a clear reason.
 */
export function SourceEditorAction({
    source,
    children,
}: {
    source: ExternalDataSource | null
    children:
        | React.ComponentType<AccessControlActionChildrenProps>
        | React.ReactElement<AccessControlActionChildrenProps>
}): JSX.Element {
    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.ExternalDataSource}
            minAccessLevel={AccessControlLevel.Editor}
            userAccessLevel={source?.user_access_level}
        >
            {children}
        </AccessControlAction>
    )
}

/**
 * Per-table variant of `SourceEditorAction`. `schema.user_access_level` is the effective level for the
 * table (it already inherits the source), so gating a row's sync/delete controls on it covers both the
 * source-level and per-table-locked cases.
 */
export function SchemaEditorAction({
    schema,
    children,
}: {
    schema: ExternalDataSourceSchema | null
    children:
        | React.ComponentType<AccessControlActionChildrenProps>
        | React.ReactElement<AccessControlActionChildrenProps>
}): JSX.Element {
    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.WarehouseTable}
            minAccessLevel={AccessControlLevel.Editor}
            userAccessLevel={schema?.user_access_level}
        >
            {children}
        </AccessControlAction>
    )
}
