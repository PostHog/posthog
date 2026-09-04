import {
    IconBook,
    IconDatabase,
    IconDownload,
    IconGraph,
    IconHome,
    IconList,
    IconPulse,
    IconServer,
    IconTerminal,
} from '@posthog/icons'
import { LemonBadge, LemonButton, LemonDivider } from '@posthog/lemon-ui'

export type ContextWarehouseSection =
    | 'home'
    | 'sql'
    | 'sources'
    | 'models'
    | 'catalog'
    | 'batch-exports'
    | 'monitoring'
    | 'findings'
    | 'compute'

type ContextWarehouseRailProps = {
    activeSection: ContextWarehouseSection
    findingCount: number
    onSectionChange: (section: ContextWarehouseSection) => void
}

type RailItem = {
    section: ContextWarehouseSection
    label: string
    icon: JSX.Element
}

type RailGroup = {
    label: string
    items: RailItem[]
}

const RAIL_GROUPS: RailGroup[] = [
    {
        label: 'Workspace',
        items: [
            { section: 'home', label: 'Home', icon: <IconHome /> },
            { section: 'sql', label: 'SQL editor', icon: <IconTerminal /> },
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

export function ContextWarehouseRail({
    activeSection,
    findingCount,
    onSectionChange,
}: ContextWarehouseRailProps): JSX.Element {
    return (
        <nav
            aria-label="Context warehouse sections"
            className="grid w-full shrink-0 grid-cols-2 gap-x-4 gap-y-3 @min-[64rem]/context-warehouse:flex @min-[64rem]/context-warehouse:w-56 @min-[64rem]/context-warehouse:flex-col @min-[64rem]/context-warehouse:gap-0"
        >
            {RAIL_GROUPS.map((group, groupIndex) => (
                <div key={group.label} className="min-w-0">
                    <div className="px-2 pb-1 pt-1 text-xs font-semibold uppercase tracking-wide text-secondary">
                        {group.label}
                    </div>
                    <div className="flex flex-col gap-1">
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
                                        <LemonBadge.Number count={findingCount} maxDigits={2} showZero size="small" />
                                    ) : undefined
                                }
                            >
                                {item.label}
                            </LemonButton>
                        ))}
                    </div>
                    {groupIndex < RAIL_GROUPS.length - 1 ? <LemonDivider className="my-3" /> : null}
                </div>
            ))}
        </nav>
    )
}
