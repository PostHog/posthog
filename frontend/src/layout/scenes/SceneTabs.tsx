import { cn } from 'lib/utils/css-classes'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconPlus, IconX } from '@posthog/icons'

import { useActions, useValues } from 'kea'
import { sceneTabsLogic, SceneTab } from '~/layout/scenes/sceneTabsLogic'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { DndContext, PointerSensor, useSensor, useSensors, DragEndEvent } from '@dnd-kit/core'
import { SortableContext, useSortable, horizontalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'

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
                'flex items-center w-full sticky top-0 bg-surface-secondary z-[var(--z-top-navigation)] border-b border-primary',
                className
            )}
        >
            <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
                <SortableContext items={[...tabs.map((t) => t.id), 'new']} strategy={horizontalListSortingStrategy}>
                    <div className={cn('flex flex-row flex-wrap', className)}>
                        {tabs.map((tab) => (
                            <SortableSceneTab key={tab.id} tab={tab} />
                        ))}
                        <Link
                            to={urls.newTab()}
                            className="rounded-none px-2 py-1.5 text-primary hover:text-primary-hover hover:bg-surface-primary focus:text-primary-hover focus:outline-none"
                            data-attr="scene-tab-new-button"
                            onClick={(e) => {
                                e.preventDefault()
                                newTab()
                            }}
                        >
                            <IconPlus className="!ml-0" fontSize={14} />
                        </Link>
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
                'deprecated-space-y-px p-1 flex border-b-2 flex-row items-center gap-1 cursor-pointer',
                tab.active
                    ? 'text-primary bg-surface-primary !border-brand-yellow'
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
