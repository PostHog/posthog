import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconGear } from '@posthog/icons'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonSelect, LemonSelectOption } from 'lib/lemon-ui/LemonSelect'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
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
    const connectionSelectorValue = getConnectionSelectorValue(connectionOptionsLoading, selectedConnectionId)
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
        <div className="flex flex-col gap-1 flex-1 min-w-0">
            <LemonSelect
                size="small"
                fullWidth
                // Long connection names must fit within the resizable database sidebar.
                className="min-w-0"
                truncateText={{ maxWidthClass: 'max-w-full' }}
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
                            connectionId: nextValue,
                            sendRawQuery: undefined,
                        },
                    } as typeof sourceQuery)
                    syncUrlWithQuery()
                }}
                options={displayedConnectionSelectOptions.map((group) => ({
                    options: group.options.map(toLemonSelectOption),
                }))}
            />
            {!selectedConnectionId && (
                <div className="flex items-center gap-1 text-xs text-secondary">
                    Default schema:
                    <Tooltip
                        title={
                            <>
                                Table names without a schema resolve in <code>posthog</code> first. For example,{' '}
                                <code>events</code> uses <code>posthog.events</code>. Use a qualified table name to
                                query another schema.
                            </>
                        }
                    >
                        <LemonTag type="muted" size="small" weight="normal" tabIndex={0}>
                            <code>posthog</code>
                        </LemonTag>
                    </Tooltip>
                </div>
            )}
        </div>
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
