import { cn } from 'lib/utils/css-classes'

import { TodayWarehouseTabsPane } from './TodayWarehouseTabsPane'

/** The warehouse sidebar on desktop. It sits under the warehouse header beside the page, so its tabs read as part of that page. */
export function TodayWarehouseSidebar({ className }: { className?: string }): JSX.Element {
    return (
        <div
            data-quill
            className={cn('flex min-h-0 w-56 shrink-0 flex-col border-r border-[var(--border)] bg-chrome', className)}
        >
            <TodayWarehouseTabsPane />
        </div>
    )
}
