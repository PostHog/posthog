import { LemonInput, LemonSegmentedButton } from '@posthog/lemon-ui'

import { PANE_LEFT, PANE_ROW } from './paneClasses'

export function RepositoryListFilters<V extends string>({
    search,
    onSearchChange,
    view,
    views,
    onViewChange,
    children,
    actions,
    'data-attr': dataAttr,
}: {
    search: string
    onSearchChange: (search: string) => void
    view: V
    views: { value: V; label: string }[]
    onViewChange: (view: V) => void
    children?: React.ReactNode
    actions?: React.ReactNode
    'data-attr': string
}): JSX.Element {
    return (
        <div className={`col-span-full flex flex-wrap items-center gap-2 px-4 py-2.5 ${PANE_LEFT} ${PANE_ROW}`}>
            <LemonInput
                type="search"
                size="small"
                className="min-w-48 flex-1"
                placeholder="Filter repositories"
                aria-label="Filter repositories"
                value={search}
                onChange={onSearchChange}
                data-attr={dataAttr}
            />
            {children}
            <LemonSegmentedButton size="small" value={view} options={views} onChange={onViewChange} />
            {actions && <div className="ml-auto flex items-center gap-1">{actions}</div>}
        </div>
    )
}
