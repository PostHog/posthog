import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconGear } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonSelect, LemonSelectOption } from 'lib/lemon-ui/LemonSelect'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { urls } from 'scenes/urls'

import {
    ADD_DIRECT_CONNECTION_PREFIX,
    CONFIGURE_SOURCES,
    type ConnectionSelectOption,
    POSTHOG_WAREHOUSE,
    addHiddenSelectedConnectionOption,
    connectionSelectorLogic,
    getConnectionSelectorValue,
} from 'products/data_warehouse/frontend/shared/logics/connectionSelectorLogic'

import { sqlEditorLogic } from './sqlEditorLogic'

const sourceIcon = (src: string): JSX.Element => (
    <img src={src} alt="" width={16} height={16} className="object-contain rounded" />
)

interface ConnectionSelectorProps {
    tabId: string
}

export function ConnectionSelector({ tabId }: ConnectionSelectorProps): JSX.Element | null {
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
    const connectionSelectorValue =
        sourceQuery.source.executionTarget === 'managed_trino'
            ? 'managed_trino'
            : getConnectionSelectorValue(connectionOptionsLoading, selectedConnectionId)
    const displayedConnectionSelectOptions = addHiddenSelectedConnectionOption(
        connectionSelectOptions,
        connectionOptions,
        connectionOptionsLoading,
        selectedConnectionId
    )
    // Strip the legacy top-level connectionId so source.connectionId stays canonical.
    const { connectionId: _legacyConnectionId, ...sourceQueryWithoutLegacyConnectionId } =
        sourceQuery as typeof sourceQuery & {
            connectionId?: string
        }

    return (
        <LemonSelect
            data-attr="sql-editor-connection-selector"
            size="small"
            fullWidth
            // min-w-0 lets the flex item shrink past the label's min-content width, and
            // truncateText ellipsizes the label — a long source name (e.g. "managed_warehouse
            // (DuckDB)") otherwise wraps and spills out of the narrow database-tree sidebar.
            className="flex-1 min-w-0"
            truncateText={{ maxWidthClass: 'max-w-full' }}
            value={connectionSelectorValue}
            onChange={(nextValue) => {
                if (nextValue === 'managed_trino') {
                    setExecutionTarget('managed_trino')
                    return
                }
                if (!nextValue || nextValue === POSTHOG_WAREHOUSE) {
                    setSourceQuery({
                        ...sourceQueryWithoutLegacyConnectionId,
                        source: {
                            ...sourceQuery.source,
                            executionTarget: undefined,
                            connectionId: undefined,
                            sendRawQuery: undefined,
                        },
                    } as typeof sourceQuery)
                    syncUrlWithQuery()
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

                // sqlEditorLogic's selectedConnectionId subscription re-enables raw SQL mode
                // for raw-only (supports_hogql=false) connections.
                setSourceQuery({
                    ...sourceQueryWithoutLegacyConnectionId,
                    source: {
                        ...sourceQuery.source,
                        executionTarget: undefined,
                        connectionId: nextValue,
                        sendRawQuery: undefined,
                    },
                } as typeof sourceQuery)
                syncUrlWithQuery()
            }}
            options={[
                ...displayedConnectionSelectOptions.map((group) => ({
                    options: group.options.map(toLemonSelectOption),
                })),
                ...(hostedTrinoEnabled || sourceQuery.source.executionTarget === 'managed_trino'
                    ? [
                          {
                              options: [
                                  {
                                      label: 'Hosted Trino',
                                      value: 'managed_trino',
                                      disabledReason: hostedTrinoEnabled
                                          ? undefined
                                          : 'Hosted Trino queries are not enabled for this organization',
                                  },
                              ],
                          },
                      ]
                    : []),
            ]}
        />
    )
}

// A connection option is either a leaf (selectable `value`) or a node with nested `options` that
// LemonSelect renders as a submenu (e.g. "Add direct connection" → Postgres / MySQL / Snowflake).
function toLemonSelectOption(option: ConnectionSelectOption): LemonSelectOption<string> {
    const icon = option.iconSrc ? sourceIcon(option.iconSrc) : undefined
    if (option.options) {
        return { label: option.label, icon, options: option.options.map(toLemonSelectOption) }
    }
    return {
        value: option.value as string,
        label: option.label,
        icon,
        hidden: option.hidden,
        sideAction: option.managementUrl
            ? {
                  onClick: () => newInternalTab(option.managementUrl),
                  icon: <IconGear />,
                  tooltip: 'Open source settings',
                  'aria-label': `Open settings for ${option.label}`,
                  'data-attr': 'connection-selector-source-settings',
              }
            : undefined,
    }
}
