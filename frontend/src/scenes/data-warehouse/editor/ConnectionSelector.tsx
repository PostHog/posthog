import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { urls } from 'scenes/urls'

import {
    ADD_POSTGRES_DIRECT_CONNECTION,
    CONFIGURE_SOURCES,
    POSTHOG_WAREHOUSE,
    connectionSelectorLogic,
} from './connectionSelectorLogic'
import { sqlEditorLogic } from './sqlEditorLogic'

const sourceIcon = (src: string): JSX.Element => (
    <img src={src} alt="" width={16} height={16} className="object-contain rounded" />
)

export function ConnectionSelector(): JSX.Element | null {
    const { sourceQuery, selectedConnectionId } = useValues(sqlEditorLogic)
    const { connectionSelectOptions, connectionSelectorValue, isDirectQueryEnabled } = useValues(
        connectionSelectorLogic({ selectedConnectionId })
    )
    const { setSourceQuery, syncUrlWithQuery } = useActions(sqlEditorLogic)
    // Strip the legacy top-level connectionId so source.connectionId stays canonical.
    const { connectionId: _legacyConnectionId, ...sourceQueryWithoutLegacyConnectionId } =
        sourceQuery as typeof sourceQuery & {
            connectionId?: string
        }

    if (!isDirectQueryEnabled) {
        return null
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
                    router.actions.push(urls.dataWarehouseSourceNew('Postgres'))
                    return
                }

                if (nextValue === CONFIGURE_SOURCES) {
                    router.actions.push(urls.sources())
                    return
                }

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
                options: group.options.map((option) => ({
                    ...option,
                    icon: option.iconSrc ? sourceIcon(option.iconSrc) : undefined,
                })),
            }))}
        />
    )
}
