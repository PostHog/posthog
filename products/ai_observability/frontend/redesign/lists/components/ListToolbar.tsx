import { ReactNode } from 'react'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

export interface ListToolbarProps {
    search: string
    onSearchChange?: (search: string) => void
    searchPlaceholder: string
    filters: ReactNode
    testAccounts: ReactNode
    dateRange: ReactNode
    onReload: () => void
    reloading: boolean
    'data-attr': string
}

export function ListToolbar({
    search,
    onSearchChange,
    searchPlaceholder,
    filters,
    testAccounts,
    dateRange,
    onReload,
    reloading,
    'data-attr': dataAttr,
}: ListToolbarProps): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-2">
            {onSearchChange ? (
                <LemonInput
                    type="search"
                    size="small"
                    className="w-64 max-w-full"
                    value={search}
                    onChange={onSearchChange}
                    placeholder={searchPlaceholder}
                    aria-label={searchPlaceholder}
                    // pinned: autocapture dashboards and tests select the search box by this value
                    data-attr={`${dataAttr}-search`}
                />
            ) : null}
            {filters}
            {testAccounts}
            <div className="ml-auto flex flex-wrap items-center gap-2">
                {dateRange}
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconRefresh />}
                    onClick={onReload}
                    loading={reloading}
                    // pinned: autocapture dashboards and tests select the reload button by this value
                    data-attr={`${dataAttr}-reload`}
                >
                    Reload
                </LemonButton>
            </div>
        </div>
    )
}
