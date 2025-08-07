import { IconPlus, IconX } from '@posthog/icons'
import { cn } from 'lib/utils/css-classes'

import { useActions, useValues } from 'kea'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'
import { SceneTab, sceneTabsLogic } from '~/layout/scenes/sceneTabsLogic'

import { DndContext, DragEndEvent, PointerSensor, useSensor, useSensors } from '@dnd-kit/core'
import { horizontalListSortingStrategy, SortableContext, useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ProjectDropdownMenu } from '../panel-layout/ProjectDropdownMenu'

export interface SceneTabsProps {
    className?: string
}

export function SceneTabs({ className }: SceneTabsProps): JSX.Element {
    const { tabs } = useValues(sceneTabsLogic)
    const { newTab, reorderTabs } = useActions(sceneTabsLogic)

    const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }))

    const handleDragEnd = ({ active, over }: DragEndEvent): void => {
        if (over && active.id !== over.id) {
            reorderTabs(active.id as string, over.id as string)
        }
    }

    return (
        <div
            className={cn(
                'flex items-center w-full sticky top-0 bg-surface-tertiary z-[var(--z-top-navigation)] px-1.5 border-b border-primary',
                className
            )}
        >
            <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
                <SortableContext items={[...tabs.map((t) => t.id), 'new']} strategy={horizontalListSortingStrategy}>
                    <div className={cn('flex flex-row flex-wrap gap-1 pt-1', className)}>
                        <div className="flex items-center gap-1">
                            <ProjectDropdownMenu
                                buttonProps={{
                                    className: 'h-[32px] mt-[-2px]',
                                }}
                            />
                        </div>
                        {tabs.map((tab) => (
                            <SortableSceneTab key={tab.id} tab={tab} />
                        ))}
                        <div className="py-1">
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
        <div ref={setNodeRef} style={style} {...attributes} {...listeners}>
            <SceneTabComponent tab={tab} isDragging={isDragging} />
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
    const { clickOnTab, removeTab } = useActions(sceneTabsLogic)
    return (
        <Link
            onClick={(e) => {
                e.stopPropagation()
                e.preventDefault()
                if (!isDragging) {
                    clickOnTab(tab)
                }
            }}
            to={isDragging ? undefined : `${tab.pathname}${tab.search}${tab.hash}`}
            className={cn(
                'h-[37px] p-0.5 flex flex-row items-center gap-1 rounded-tr rounded-tl border border-transparent bottom-[-1px] relative',
                tab.active
                    ? 'cursor-default text-primary bg-surface-secondary border-primary border-b-transparent'
                    : 'cursor-pointer text-secondary bg-transparent hover:bg-surface-primary hover:text-primary-hover',
                canRemoveTab ? 'pl-2 pr-1' : 'px-3',
                'focus:outline-none',
                className
            )}
        >
            <div className="flex-grow text-left whitespace-pre">{tab.title}</div>
            {canRemoveTab && (
                <ButtonPrimitive
                    onClick={(e) => {
                        e.stopPropagation()
                        e.preventDefault()
                        removeTab(tab)
                    }}
                    iconOnly
                    size="xs"
                >
                    <IconX />
                </ButtonPrimitive>
            )}
        </Link>
    )
}
