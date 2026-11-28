import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import {
    ADD_DIRECT_CONNECTION_PREFIX,
    CONFIGURE_SOURCES,
    type ConnectionSelectOptionGroup,
    POSTHOG_WAREHOUSE,
    addHiddenSelectedConnectionOption,
    connectionSelectorLogic,
    getConnectionSelectorValue,
} from 'products/data_warehouse/frontend/shared/logics/connectionSelectorLogic'

import { sqlEditorLogic } from './sqlEditorLogic'

export const MANAGED_TRINO_CONNECTION = 'managed_trino'

export interface ConnectionSelectorState {
    value: string | null
    groups: ConnectionSelectOptionGroup[]
    /** Whether "PostHog (Trino)" is listed under PostHog, and why it can't be picked if so. */
    showManagedTrino: boolean
    managedTrinoDisabledReason: string | undefined
    select: (value: string | null) => void
}

/** The connection picker's options and what picking one does, shared by the Lemon and quill pickers. */
export function useConnectionSelectorState(tabId: string): ConnectionSelectorState {
    const logic = sqlEditorLogic({ tabId })
    const { sourceQuery, selectedConnectionId } = useValues(logic)
    const { connectionOptions, connectionOptionsLoading, connectionSelectOptions } =
        useValues(connectionSelectorLogic())
    const { maybeLoadConnectionOptions } = useActions(connectionSelectorLogic())
    const { setSourceQuery, syncUrlWithQuery, setExecutionTarget } = useActions(logic)
    const { featureFlags } = useValues(featureFlagLogic)
    const hostedTrinoEnabled = !!featureFlags[FEATURE_FLAGS.MANAGED_TRINO_QUERY]

    useOnMountEffect(() => {
        maybeLoadConnectionOptions()
    })

    // Strip the legacy top-level connectionId so source.connectionId stays canonical.
    const { connectionId: _legacyConnectionId, ...sourceQueryWithoutLegacyConnectionId } =
        sourceQuery as typeof sourceQuery & {
            connectionId?: string
        }

    const selectConnection = (connectionId: string | undefined): void => {
        // sqlEditorLogic's selectedConnectionId subscription re-enables raw SQL mode
        // for raw-only (supports_hogql=false) connections.
        setSourceQuery({
            ...sourceQueryWithoutLegacyConnectionId,
            source: {
                ...sourceQuery.source,
                executionTarget: undefined,
                connectionId,
                sendRawQuery: undefined,
            },
        } as typeof sourceQuery)
        syncUrlWithQuery()
    }

    return {
        value:
            sourceQuery.source.executionTarget === MANAGED_TRINO_CONNECTION
                ? MANAGED_TRINO_CONNECTION
                : getConnectionSelectorValue(connectionOptionsLoading, selectedConnectionId),
        groups: addHiddenSelectedConnectionOption(
            connectionSelectOptions,
            connectionOptions,
            connectionOptionsLoading,
            selectedConnectionId
        ),
        showManagedTrino: hostedTrinoEnabled || sourceQuery.source.executionTarget === MANAGED_TRINO_CONNECTION,
        managedTrinoDisabledReason: hostedTrinoEnabled
            ? undefined
            : 'PostHog (Trino) queries are not enabled for this organization',
        select: (nextValue) => {
            if (nextValue === MANAGED_TRINO_CONNECTION) {
                setExecutionTarget(MANAGED_TRINO_CONNECTION)
                return
            }
            if (!nextValue || nextValue === POSTHOG_WAREHOUSE) {
                selectConnection(undefined)
                return
            }
            if (nextValue.startsWith(ADD_DIRECT_CONNECTION_PREFIX)) {
                const sourceType = nextValue.slice(ADD_DIRECT_CONNECTION_PREFIX.length)
                router.actions.push(urls.dataWarehouseSourceNew(sourceType, undefined, undefined, 'direct'))
                return
            }
            if (nextValue === CONFIGURE_SOURCES) {
                router.actions.push(urls.sources())
                return
            }
            selectConnection(nextValue)
        },
    }
}
