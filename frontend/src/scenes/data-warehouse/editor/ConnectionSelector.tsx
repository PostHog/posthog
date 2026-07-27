import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconGear } from '@posthog/icons'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonSelect, LemonSelectOption } from 'lib/lemon-ui/LemonSelect'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { urls } from 'scenes/urls'

import {
    ADD_MYSQL_DIRECT_CONNECTION,
    ADD_POSTGRES_DIRECT_CONNECTION,
    ADD_REDSHIFT_DIRECT_CONNECTION,
    ADD_SNOWFLAKE_DIRECT_CONNECTION,
    CONFIGURE_SOURCES,
    type ConnectionSelectOption,
    POSTHOG_WAREHOUSE,
    connectionSelectorLogic,
    getConnectionSelectorValue,
} from './connectionSelectorLogic'
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
    const { setSourceQuery, syncUrlWithQuery } = useActions(logic)

    useOnMountEffect(() => {
        maybeLoadConnectionOptions()
    })
    const connectionSelectorValue = getConnectionSelectorValue(
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
            size="small"
            fullWidth
            className="flex-1"
            value={connectionSelectorValue}
            onChange={(nextValue) => {
                if (!nextValue || nextValue === POSTHOG_WAREHOUSE) {
                    setSourceQuery({
                        ...sourceQueryWithoutLegacyConnectionId,
                        source: {
                            ...sourceQuery.source,
                            connectionId: undefined,
                            sendRawQuery: undefined,
                        },
                    } as typeof sourceQuery)
                    syncUrlWithQuery()
                    return
                }

                if (nextValue === ADD_POSTGRES_DIRECT_CONNECTION) {
                    router.actions.push(urls.dataWarehouseSourceNew('Postgres', undefined, undefined, 'direct'))
                    return
                }

                if (nextValue === ADD_MYSQL_DIRECT_CONNECTION) {
                    router.actions.push(urls.dataWarehouseSourceNew('MySQL', undefined, undefined, 'direct'))
                    return
                }

                if (nextValue === ADD_SNOWFLAKE_DIRECT_CONNECTION) {
                    router.actions.push(urls.dataWarehouseSourceNew('Snowflake', undefined, undefined, 'direct'))
                    return
                }

                if (nextValue === ADD_REDSHIFT_DIRECT_CONNECTION) {
                    router.actions.push(urls.dataWarehouseSourceNew('Redshift', undefined, undefined, 'direct'))
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
                        connectionId: nextValue,
                        sendRawQuery: undefined,
                    },
                } as typeof sourceQuery)
                syncUrlWithQuery()
            }}
            options={connectionSelectOptions.map((group) => ({
                options: group.options.map(toLemonSelectOption),
            }))}
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
