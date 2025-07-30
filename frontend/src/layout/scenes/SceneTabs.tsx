import { cn } from 'lib/utils/css-classes'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconPlus, IconX } from '@posthog/icons'
import { router } from 'kea-router'
import { useActions, useValues } from 'kea'
import { sceneTabsLogic, SceneTab } from '~/layout/scenes/sceneTabsLogic'

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
                {tabs.map((tab) => (
                    <SceneTabComponent tab={tab} />
                ))}
            </div>
            <LemonButton
                className="rounded-none"
                onClick={() => newTab()}
                icon={<IconPlus fontSize={14} />}
                data-attr="sql-editor-new-tab-button"
            />
        </div>
    )
}

interface SceneTabProps {
    tab: SceneTab
    className?: string
}

function SceneTabComponent({ tab, className }: SceneTabProps): JSX.Element {
    const canRemoveTab = true
    const { persistTab, removeTab } = useActions(sceneTabsLogic)
    return (
        <div
            onClick={() => {
                persistTab(tab)
                router.actions.push(tab.pathname, tab.search, tab.hash)
            }}
            className={cn(
                'deprecated-space-y-px p-1 flex border-b-2 flex-row items-center gap-1 hover:bg-surface-primary cursor-pointer',
                tab.active
                    ? 'bg-surface-primary border-b-2 !border-brand-yellow'
                    : 'bg-surface-secondary border-transparent',
                canRemoveTab ? 'pl-3 pr-2' : 'px-3',
                tab.persist ? '' : 'italic',
                className
            )}
        >
            <div className="flex-grow text-left whitespace-pre">{tab.title}</div>
            {canRemoveTab && (
                <LemonButton
                    onClick={(e) => {
                        e.stopPropagation()
                        removeTab(tab)
                    }}
                    size="xsmall"
                    icon={<IconX />}
                />
            )}
        </div>
    )
}
