import { cn } from 'lib/utils/css-classes'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconPlus, IconX } from '@posthog/icons'

import { useActions, useValues } from 'kea'
import { sceneTabsLogic, SceneTab } from '~/layout/scenes/sceneTabsLogic'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

export interface SceneTabsProps {
    className?: string
}

export function SceneTabs({ className }: SceneTabsProps): JSX.Element {
    const { tabs } = useValues(sceneTabsLogic)
    const { newTab } = useActions(sceneTabsLogic)

    return (
        <div
            className={cn(
                'flex items-center w-full sticky top-0 bg-surface-secondary z-[var(--z-top-navigation)] border-b border-primary h-[var(--scene-layout-header-height)]',
                className
            )}
        >
            <div className={cn('flex flex-row overflow-auto hide-scrollbar h-[40px]', className)}>
                {tabs.map((tab, index) => (
                    <SceneTabComponent key={index} tab={tab} />
                ))}
            </div>
            <Link
                to={urls.newTab()}
                className="rounded-none px-1.5 pt-0.5 pb-1 text-primary hover:text-primary-hover focus:text-primary-hover focus:outline-none"
                data-attr="sql-editor-new-tab-button"
                onClick={(e) => {
                    e.preventDefault()
                    newTab()
                }}
            >
                <IconPlus fontSize={14} />
            </Link>
        </div>
    )
}

interface SceneTabProps {
    tab: SceneTab
    className?: string
}

function SceneTabComponent({ tab, className }: SceneTabProps): JSX.Element {
    const canRemoveTab = true
    const { clickOnTab, removeTab } = useActions(sceneTabsLogic)
    return (
        <Link
            onClick={(e) => {
                e.preventDefault()
                clickOnTab(tab)
            }}
            to={`${tab.pathname}${tab.search}${tab.hash}`}
            className={cn(
                'deprecated-space-y-px p-1 flex border-b-2 flex-row items-center gap-1 cursor-pointer',
                tab.active
                    ? 'text-primary bg-surface-primary border-b-2 !border-brand-yellow'
                    : 'text-secondary bg-surface-secondary border-transparent',
                canRemoveTab ? 'pl-3 pr-2' : 'px-3',
                'hover:bg-surface-primary hover:text-primary-hover focus:outline-none',
                className
            )}
        >
            <div className="flex-grow text-left whitespace-pre">{tab.title}</div>
            {canRemoveTab && (
                <LemonButton
                    onClick={(e) => {
                        e.stopPropagation()
                        e.preventDefault()
                        removeTab(tab)
                    }}
                    size="xsmall"
                    icon={<IconX />}
                />
            )}
        </Link>
    )
}
