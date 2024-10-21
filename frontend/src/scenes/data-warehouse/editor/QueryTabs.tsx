import { IconPlus, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'

import { Tab } from './queryWindowLogic'

interface QueryTabsProps {
    tabs: Tab[]
    onTabClick: (tab: Tab) => void
    onTabClear: (tab: Tab) => void
    onAdd: () => void
    activeKey: string
}

export function QueryTabs({ tabs, onTabClear, onTabClick, onAdd, activeKey }: QueryTabsProps): JSX.Element {
    return (
        <div className="flex flex-row overflow-scroll hide-scrollbar">
            {tabs.map((tab: Tab) => (
                <QueryTab
                    key={tab.key}
                    tab={tab}
                    onClear={onTabClear}
                    onClick={onTabClick}
                    active={activeKey == tab.key}
                />
            ))}
            <LemonButton onClick={onAdd} icon={<IconPlus fontSize={14} />} />
        </div>
    )
}

interface QueryTabProps {
    tab: Tab
    onClick: (tab: Tab) => void
    onClear: (tab: Tab) => void
    active: boolean
}

function QueryTab({ tab, active, onClear, onClick }: QueryTabProps): JSX.Element {
    return (
        <button
            onClick={() => onClick?.(tab)}
            className={clsx(
                'space-y-px rounded-t p-1 flex flex-row items-center gap-1 hover:bg-[var(--bg-light)] cursor-pointer',
                active ? 'bg-[var(--bg-light)] border' : 'bg-bg-3000',
                'pl-3 pr-2'
            )}
        >
            Untitled
            {onClear && (
                <LemonButton
                    onClick={(e) => {
                        e.stopPropagation()
                        onClear(tab)
                    }}
                    size="xsmall"
                    icon={<IconX />}
                />
            )}
        </button>
    )
}
