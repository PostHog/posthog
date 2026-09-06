import type { ReactNode } from 'react'

import { IconChevronDown, IconGear, IconSearch } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { ContextWarehouseSidebar, type ContextWarehouseSection } from './ContextWarehouseSidebar'

type ContextWarehouseAppShellProps = {
    activeSection: ContextWarehouseSection
    findingCount: number
    onSectionChange: (section: ContextWarehouseSection) => void
    children: ReactNode
}

export function ContextWarehouseAppShell({
    activeSection,
    findingCount,
    onSectionChange,
    children,
}: ContextWarehouseAppShellProps): JSX.Element {
    return (
        <div className="flex h-screen min-h-0 w-full overflow-hidden bg-surface-tertiary">
            <aside className="flex h-full w-64 shrink-0 flex-col border-r bg-surface-tertiary">
                <div className="flex flex-col gap-1 p-2">
                    <LemonButton fullWidth sideIcon={<IconChevronDown />} size="small" type="secondary">
                        My project
                    </LemonButton>
                    <LemonButton
                        data-attr="context-warehouse-sidebar-search"
                        fullWidth
                        icon={<IconSearch />}
                        size="small"
                        type="tertiary"
                    >
                        Search
                    </LemonButton>
                </div>

                <ContextWarehouseSidebar
                    activeSection={activeSection}
                    findingCount={findingCount}
                    onSectionChange={onSectionChange}
                />

                <div className="border-t p-2">
                    <LemonButton fullWidth icon={<IconGear />} size="small" type="tertiary">
                        Settings
                    </LemonButton>
                </div>
            </aside>

            <main className="m-1 min-w-0 flex-1 overflow-y-auto rounded border bg-bg-primary p-4">{children}</main>
        </div>
    )
}
