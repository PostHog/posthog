import clsx from 'clsx'
import { useValues } from 'kea'

import {
    IconApps,
    IconChat,
    IconChevronRight,
    IconClock,
    IconDashboard,
    IconDatabase,
    IconFolderOpen,
    IconFunnels,
    IconGear,
    IconHome,
    IconLogomark,
    IconNotification,
    IconQuestion,
    IconSearch,
    IconStar,
} from '@posthog/icons'

import { onboardingLogic } from '../onboardingLogic'
import { PreviewPageView } from './pages'
import { type PreviewConfig, type SidebarItem, type SidebarSection } from './types'

function SidebarIcon({ iconKey }: { iconKey?: string }): JSX.Element {
    const iconMap: Record<string, JSX.Element> = {
        home: <IconHome />,
        activity: <IconClock />,
        data: <IconDatabase />,
        files: <IconFolderOpen className="stroke-[1.2]" />,
        apps: <IconApps />,
        starred: <IconStar />,
        inbox: <IconNotification />,
        gear: <IconGear />,
        notifications: <IconNotification />,
        help: <IconQuestion />,
        dashboard: <IconDashboard />,
        funnel: <IconFunnels />,
    }
    if (iconKey && iconMap[iconKey]) {
        return iconMap[iconKey]
    }
    return <IconApps />
}

function SidebarSectionView({ section }: { section: SidebarSection }): JSX.Element {
    return (
        <div className="flex flex-col gap-px">
            {section.title && (
                <div className="flex items-center py-1 text-xxs font-semibold text-secondary px-2">{section.title}</div>
            )}
            {section.items.map((item: SidebarItem, i: number) => (
                <div
                    key={`${item.label}-${i}`}
                    className={clsx(
                        'group flex items-center gap-2 rounded px-2 py-1 -outline-offset-2 cursor-default',
                        item.active && 'bg-fill-highlight-100 dark:bg-surface-primary'
                    )}
                >
                    <span
                        className={clsx(
                            'relative flex size-4 shrink-0 items-center justify-center transition-all duration-50',
                            item.active
                                ? 'text-primary opacity-100'
                                : 'text-secondary opacity-50 group-hover:opacity-100'
                        )}
                    >
                        <SidebarIcon iconKey={item.iconKey} />
                    </span>
                    <span
                        className={clsx(
                            'flex-1 truncate text-sm leading-none',
                            item.active ? 'text-primary' : 'text-secondary group-hover:text-primary'
                        )}
                    >
                        {item.label}
                    </span>
                    {item.active && (
                        <span className="ml-auto shrink-0 text-tertiary opacity-70">
                            <IconGear className="size-3" />
                        </span>
                    )}
                    {item.expandable && !item.active && (
                        <span className="ml-auto shrink-0 text-secondary opacity-50">
                            <IconChevronRight className="size-3" />
                        </span>
                    )}
                </div>
            ))}
        </div>
    )
}

function SidebarFooter({ items }: { items: { label: string; iconKey?: string }[] }): JSX.Element {
    return (
        <div className="relative shrink-0 bg-surface-secondary px-3 pt-2 pb-3 shadow-[0_-6px_16px_-4px_rgba(0,0,0,0.08)] before:absolute before:inset-x-0 before:top-0 before:h-px before:bg-border-primary">
            <div className="flex flex-col gap-px">
                {items.map((item) => (
                    <div key={item.label} className="group flex items-center gap-2 rounded px-2 py-1 cursor-default">
                        <span className="flex size-4 shrink-0 items-center justify-center text-secondary opacity-50 group-hover:opacity-100 transition-all duration-50">
                            <SidebarIcon iconKey={item.iconKey} />
                        </span>
                        <span className="flex-1 truncate text-sm text-secondary group-hover:text-primary leading-none">
                            {item.label}
                        </span>
                        {item.iconKey === 'notifications' && (
                            <span className="ml-auto shrink-0 text-secondary opacity-50">
                                <IconChevronRight className="size-3" />
                            </span>
                        )}
                    </div>
                ))}
            </div>
        </div>
    )
}

export function PreviewChrome({ config }: { config: PreviewConfig }): JSX.Element {
    const { previewFocus } = useValues(onboardingLogic)

    return (
        <div className="flex h-full w-full overflow-hidden rounded-xl border border-primary bg-primary shadow-lg">
            {/* Sidebar */}
            <div className="flex w-48 shrink-0 flex-col border-r border-primary bg-surface-secondary">
                <div className="flex flex-col gap-1 p-3 pb-0">
                    <div
                        className={clsx(
                            'flex items-center gap-2 py-1 px-1 rounded',
                            previewFocus === 'orgName' &&
                                'ring ring-yellow-500 ring-offset-1 ring-offset-transparent shadow-[0_0_0_4px_rgba(251,146,60,0.35),0_0_24px_6px_rgba(249,115,22,0.2)] transition-all duration-150'
                        )}
                    >
                        <IconLogomark className="size-4 shrink-0 text-secondary" />
                        <span
                            className={clsx(
                                'flex-1 truncate text-sm font-bold leading-none',
                                config.org.name.trim() ? 'text-secondary' : 'text-muted'
                            )}
                        >
                            {config.org.name.trim() || 'Your company'}
                        </span>
                        <IconSearch className="size-4 shrink-0 text-secondary opacity-50" />
                    </div>
                    <div className="mx-0.5 mb-1 mt-1 flex gap-1 rounded-lg bg-(--color-bg-fill-highlight-50) dark:bg-surface-primary p-1">
                        <div className="flex w-1/2 items-center justify-center gap-1 rounded bg-surface-secondary py-1">
                            <IconApps className="size-3.5 text-primary" />
                            <span className="text-xs text-primary">Browse</span>
                        </div>
                        <div className="flex w-1/2 items-center justify-center gap-1 rounded py-1">
                            <IconChat className="size-3.5 text-ai opacity-50" />
                            <span className="text-xs text-secondary">Chat</span>
                        </div>
                    </div>
                </div>

                <div className="flex-1 overflow-hidden space-y-2 px-3">
                    {config.sidebar.sections.map((section, i) => (
                        <SidebarSectionView key={`${section.title ?? 'no-title'}-${i}`} section={section} />
                    ))}
                </div>

                <SidebarFooter items={config.sidebar.footerItems} />
            </div>

            {/* Main */}
            <div className="flex min-w-0 flex-1 flex-col">
                <div className="min-h-0 flex-1 overflow-hidden p-3">
                    <PreviewPageView page={config.page} />
                </div>
            </div>
        </div>
    )
}
