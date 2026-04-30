import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconGear } from '@posthog/icons'

import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { newInternalTab } from 'lib/utils/newInternalTab'
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
    const { connectionSelectOptions, connectionSelectorValue } = useValues(
        connectionSelectorLogic({ selectedConnectionId })
    )
    const { setSourceQuery, syncUrlWithQuery } = useActions(sqlEditorLogic)
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
                    sideAction: option.managementUrl
                        ? {
                              onClick: () => newInternalTab(option.managementUrl),
                              icon: <IconGear />,
                              tooltip: 'Open source settings',
                              'aria-label': `Open settings for ${option.label}`,
                              'data-attr': 'connection-selector-source-settings',
                          }
                        : undefined,
                })),
            }))}
        />
    )
}
