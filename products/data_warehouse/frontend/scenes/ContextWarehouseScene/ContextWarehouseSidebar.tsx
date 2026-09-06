import {
    IconBook,
    IconChevronDown,
    IconDatabase,
    IconDownload,
    IconGraph,
    IconHome,
    IconList,
    IconNotebook,
    IconPulse,
    IconServer,
    IconTerminal,
} from '@posthog/icons'
import { LemonBadge, LemonButton, LemonDivider } from '@posthog/lemon-ui'

export type ContextWarehouseSection =
    | 'home'
    | 'sql'
    | 'notebooks'
    | 'sources'
    | 'models'
    | 'catalog'
    | 'batch-exports'
    | 'monitoring'
    | 'findings'
    | 'compute'

type ContextWarehouseSidebarProps = {
    activeSection: ContextWarehouseSection
    findingCount: number
    onSectionChange: (section: ContextWarehouseSection) => void
}

type SidebarItem = {
    section: ContextWarehouseSection
    label: string
    icon: JSX.Element
}

type SidebarGroup = {
    label: string
    items: SidebarItem[]
}

const SIDEBAR_GROUPS: SidebarGroup[] = [
    {
        label: 'Workspace',
        items: [
            { section: 'home', label: 'Home', icon: <IconHome /> },
            { section: 'sql', label: 'SQL editor', icon: <IconTerminal /> },
            { section: 'notebooks', label: 'Notebooks', icon: <IconNotebook /> },
        ],
    },
    {
        label: 'Data',
        items: [
            { section: 'sources', label: 'Data sources', icon: <IconDatabase /> },
            { section: 'models', label: 'Data models', icon: <IconGraph /> },
            { section: 'catalog', label: 'Data catalog', icon: <IconBook /> },
        ],
    },
    {
        label: 'Operations',
        items: [
            { section: 'batch-exports', label: 'Batch exports', icon: <IconDownload /> },
            { section: 'monitoring', label: 'Monitoring', icon: <IconPulse /> },
            { section: 'findings', label: 'Findings', icon: <IconList /> },
        ],
    },
    {
        label: 'Manage',
        items: [{ section: 'compute', label: 'Compute', icon: <IconServer /> }],
    },
]

export function ContextWarehouseSidebar({
    activeSection,
    findingCount,
    onSectionChange,
}: ContextWarehouseSidebarProps): JSX.Element {
    return (
        <nav aria-label="Main navigation" className="flex min-h-0 flex-1 flex-col overflow-y-auto px-2 pb-3">
            <LemonButton
                active
                aria-expanded="true"
                data-attr="context-warehouse-product"
                fullWidth
                icon={<IconDatabase />}
                sideIcon={<IconChevronDown />}
                className="mb-2"
            >
                Context warehouse
            </LemonButton>

            <div className="ml-2 border-l pl-2">
                {SIDEBAR_GROUPS.map((group, groupIndex) => (
                    <div key={group.label}>
                        <div className="px-2 pb-1 pt-1 text-xxs font-semibold uppercase tracking-wide text-secondary">
                            {group.label}
                        </div>
                        <div className="flex flex-col gap-px">
                            {group.items.map((item) => (
                                <LemonButton
                                    key={item.section}
                                    active={activeSection === item.section}
                                    aria-pressed={activeSection === item.section}
                                    data-attr={`context-warehouse-nav-${item.section}`}
                                    fullWidth
                                    icon={item.icon}
                                    onClick={() => onSectionChange(item.section)}
                                    sideIcon={
                                        item.section === 'findings' ? (
                                            <LemonBadge.Number
                                                count={findingCount}
                                                maxDigits={2}
                                                showZero
                                                size="small"
                                            />
                                        ) : undefined
                                    }
                                    size="small"
                                >
                                    {item.label}
                                </LemonButton>
                            ))}
                        </div>
                        {groupIndex < SIDEBAR_GROUPS.length - 1 ? <LemonDivider className="my-2" /> : null}
                    </div>
                ))}
            </div>
        </nav>
    )
}
