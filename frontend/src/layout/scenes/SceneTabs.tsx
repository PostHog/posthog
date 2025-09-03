import { DndContext, DragEndEvent, PointerSensor, useSensor, useSensors } from '@dnd-kit/core'
import { SortableContext, horizontalListSortingStrategy, useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useActions, useValues } from 'kea'

import { IconPlus, IconSearch, IconX } from '@posthog/icons'

import { commandBarLogic } from 'lib/components/CommandBar/commandBarLogic'
import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'
import { SceneTab } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { SceneTabContextMenu } from '~/layout/scenes/SceneTabContextMenu'
import { sceneLogic } from '~/scenes/sceneLogic'

import { panelLayoutLogic } from '../panel-layout/panelLayoutLogic'

export interface SceneTabsProps {
    className?: string
}

export function SceneTabs({ className }: SceneTabsProps): JSX.Element {
    const { tabs } = useValues(sceneLogic)
    const { newTab, reorderTabs } = useActions(sceneLogic)
    const { toggleSearchBar } = useActions(commandBarLogic)
    const { isLayoutPanelPinned } = useValues(panelLayoutLogic)

    const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }))

    const handleDragEnd = ({ active, over }: DragEndEvent): void => {
        if (over && active.id !== over.id) {
            reorderTabs(active.id as string, over.id as string)
        }
    }

    return (
        <div
            className={cn(
                'flex items-center w-full bg-surface-tertiary z-[var(--z-top-navigation)] pr-1.5 border-b border-primary relative',
                className
            )}
        >
            {/* rounded corner on the left to make scene curve into tab line */}
            {!isLayoutPanelPinned && (
                <div className="absolute left-0 -bottom-1 size-2 bg-surface-tertiary">
                    <div className="relative -bottom-1 size-2 border-l border-t border-primary rounded-tl bg-primary" />
                </div>
            )}

            <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
                <SortableContext items={[...tabs.map((t) => t.id), 'new']} strategy={horizontalListSortingStrategy}>
                    <div className={cn('flex flex-row gap-1 pt-1 max-w-full items-center', className)}>
                        <div className="py-1 pl-[2px] shrink-0">
                            <ButtonPrimitive
                                iconOnly
                                onClick={toggleSearchBar}
                                data-attr="tree-navbar-search-button"
                                size="sm"
                                tooltip={
                                    <div className="flex flex-col gap-0.5">
                                        <span>
                                            For search, press <KeyboardShortcut command k />
                                        </span>
                                        <span>
                                            For commands, press <KeyboardShortcut command shift k />
                                        </span>
                                    </div>
                                }
                            >
                                <IconSearch className="text-secondary size-4" />
                            </ButtonPrimitive>
                        </div>
                        <div className="flex flex-row flex-1 min-w-0">
                            {tabs.map((tab) => (
                                <SortableSceneTab key={tab.id} tab={tab} />
                            ))}
                        </div>
                        <div className="py-1 shrink-0">
                            <Link
                                to={urls.newTab()}
                                data-attr="scene-tab-new-button"
                                onClick={(e) => {
                                    e.preventDefault()
                                    newTab()
                                }}
                                buttonProps={{
                                    size: 'sm',
                                    className:
                                        'p-1 flex flex-row items-center gap-1 cursor-pointer rounded-tr rounded-tl border-b',
                                    iconOnly: true,
                                }}
                                tooltip={
                                    <>
                                        New tab <KeyboardShortcut command b />
                                    </>
                                }
                            >
                                <IconPlus className="!ml-0" fontSize={14} />
                            </Link>
                        </div>
                    </div>
                </SortableContext>
            </DndContext>
        </div>
    )
}

function SortableSceneTab({ tab }: { tab: SceneTab }): JSX.Element {
    const { setNodeRef, attributes, listeners, transform, transition, isDragging } = useSortable({ id: tab.id })
    const style: React.CSSProperties = {
        transform: CSS.Translate.toString(transform),
        transition,
        opacity: isDragging ? 0.5 : undefined,
    }

    return (
        <div
            ref={setNodeRef}
            style={style}
            {...attributes}
            {...listeners}
            className="grow-0 shrink basis-auto min-w-[40px] max-w-[200px]"
        >
            <SceneTabContextMenu tab={tab}>
                <SceneTabComponent tab={tab} isDragging={isDragging} />
            </SceneTabContextMenu>
        </div>
    )
}

interface SceneTabProps {
    tab: SceneTab
    className?: string
    isDragging?: boolean
}

function SceneTabComponent({ tab, className, isDragging }: SceneTabProps): JSX.Element {
    const canRemoveTab = true
    const { clickOnTab, removeTab, renameTab } = useActions(sceneLogic)
    return (
        <Link
            onClick={(e) => {
                e.stopPropagation()
                e.preventDefault()
                if (!isDragging) {
                    clickOnTab(tab)
                }
            }}
            onAuxClick={(e) => {
                e.stopPropagation()
                e.preventDefault()
                if (e.button === 1 && !isDragging) {
                    removeTab(tab)
                }
            }}
            onDoubleClick={(e) => {
                e.stopPropagation()
                e.preventDefault()
                if (!isDragging) {
                    renameTab(tab)
                }
            }}
            to={isDragging ? undefined : `${tab.pathname}${tab.search}${tab.hash}`}
            className={cn(
                'w-full',
                'h-[37px] p-0.5 flex flex-row items-center gap-1 rounded-tr rounded-tl border border-transparent bottom-[-1px] relative',
                tab.active
                    ? 'cursor-default text-primary bg-primary border-primary border-b-transparent'
                    : 'cursor-pointer text-secondary bg-transparent hover:bg-surface-primary hover:text-primary-hover',
                canRemoveTab ? 'pl-2 pr-1' : 'px-3',
                'focus:outline-none',
                className
            )}
        >
            <div className={cn('flex-grow text-left max-w-[200px] truncate', tab.customTitle && 'italic')}>
                {tab.customTitle || tab.title}
            </div>
            {canRemoveTab && (
                <ButtonPrimitive
                    onClick={(e) => {
                        e.stopPropagation()
                        e.preventDefault()
                        removeTab(tab)
                    }}
                    iconOnly
                    size="xs"
                    tooltip={
                        tab.active ? (
                            <>
                                Close active tab <KeyboardShortcut shift command b />
                            </>
                        ) : (
                            'Close tab'
                        )
                    }
                >
                    <IconX />
                </ButtonPrimitive>
            )}
        </Link>
    )
}
