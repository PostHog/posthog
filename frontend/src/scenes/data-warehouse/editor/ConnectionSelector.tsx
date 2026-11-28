import { IconGear } from '@posthog/icons'

import { LemonSelect, LemonSelectOption } from 'lib/lemon-ui/LemonSelect'
import { newInternalTab } from 'lib/utils/newInternalTab'

import {
    type ConnectionSelectOption,
    POSTHOG_WAREHOUSE,
} from 'products/data_warehouse/frontend/shared/logics/connectionSelectorLogic'

import { MANAGED_TRINO_CONNECTION, useConnectionSelectorState } from './useConnectionSelectorState'

const sourceIcon = (src: string): JSX.Element => (
    <img src={src} alt="" width={16} height={16} className="object-contain rounded" />
)

interface ConnectionSelectorProps {
    tabId: string
}

export function ConnectionSelector({ tabId }: ConnectionSelectorProps): JSX.Element | null {
    const { value, groups, showManagedTrino, managedTrinoDisabledReason, select } = useConnectionSelectorState(tabId)

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
            value={value}
            onChange={select}
            options={groups.map((group) => ({
                options: group.options.flatMap((option) => {
                    const connectionOption = toLemonSelectOption(option)
                    if (option.value === POSTHOG_WAREHOUSE && showManagedTrino) {
                        return [
                            connectionOption,
                            {
                                label: 'PostHog (Trino)',
                                value: MANAGED_TRINO_CONNECTION,
                                icon: connectionOption.icon,
                                disabledReason: managedTrinoDisabledReason,
                            },
                        ]
                    }
                    return [connectionOption]
                }),
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
