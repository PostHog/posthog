import '~/layout/scenes/SceneTabs.css'

import { DndContext, DragEndEvent, PointerSensor, useSensor, useSensors } from '@dnd-kit/core'
import { SortableContext, horizontalListSortingStrategy, useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import React, { useEffect, useRef, useState } from 'react'

import { IconPlus, IconX } from '@posthog/icons'

import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { IconMenu } from 'lib/lemon-ui/icons'
import { ButtonGroupPrimitive, ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'
import { SceneTab } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { SceneTabContextMenu } from '~/layout/scenes/SceneTabContextMenu'
import { FileSystemIconType } from '~/queries/schema/schema-general'
import { sceneLogic } from '~/scenes/sceneLogic'

import { navigationLogic } from '../navigation/navigationLogic'
import { panelLayoutLogic } from '../panel-layout/panelLayoutLogic'
import { ConfigurePinnedTabsModal } from './ConfigurePinnedTabsModal'

export function SceneTabs(): JSX.Element {
    const { tabs } = useValues(sceneLogic)
    const { newTab, reorderTabs } = useActions(sceneLogic)
    const { mobileLayout } = useValues(navigationLogic)
    const { showLayoutNavBar } = useActions(panelLayoutLogic)
    const { isLayoutNavbarVisibleForMobile } = useValues(panelLayoutLogic)
    // Get the focus action from the newTabSceneLogic for the active tab
    const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }))
    const [isConfigurePinnedTabsOpen, setIsConfigurePinnedTabsOpen] = useState(false)

    const handleDragEnd = ({ active, over }: DragEndEvent): void => {
        if (!over || over.id === 'new' || active.id === over.id) {
            return
        }

        const activeIndex = active.data.current?.index
        const overIndex = over.data.current?.index

        if (typeof activeIndex !== 'number' || typeof overIndex !== 'number') {
            return
        }

        const activeTab = tabs[activeIndex]
        const overTab = tabs[overIndex]
        if (!activeTab || !overTab) {
            return
        }

        if (!!activeTab.pinned !== !!overTab.pinned) {
            return
        }

        reorderTabs(activeTab.id, overTab.id)
    }

    return (
        <div className="h-[var(--scene-layout-header-height)] flex items-center w-full min-w-0 bg-surface-primary lg:bg-surface-tertiary z-[var(--z-top-navigation)] pr-1.5 relative">
            {/* Mobile button to show/hide the layout navbar */}
            {mobileLayout && (
                <ButtonPrimitive
                    onClick={() => showLayoutNavBar(!isLayoutNavbarVisibleForMobile)}
                    iconOnly
                    className="ml-1 z-20 rounded-lg mr-1"
                >
                    {isLayoutNavbarVisibleForMobile ? <IconX /> : <IconMenu />}
                </ButtonPrimitive>
            )}

            <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
                <SortableContext
                    items={[...tabs.map((tab, index) => getSortableId(tab, index)), 'new']}
                    strategy={horizontalListSortingStrategy}
                >
                    <ScrollableShadows
                        direction="horizontal"
                        className="w-full min-w-0"
                        innerClassName={cn(
                            'scene-tab-row min-w-0 gap-1 items-center flex w-full overflow-x-auto show-scrollbar-on-hover h-[var(--scene-layout-header-height)] lg:h-auto'
                        )}
                        style={{ WebkitOverflowScrolling: 'touch' }}
                        styledScrollbars
                    >
                        {tabs.map((tab, index) => {
                            const sortableId = getSortableId(tab, index)
                            const isLastPinned =
                                tab.pinned &&
                                // last tab OR next tab is not pinned
                                (index === tabs.length - 1 || !tabs[index + 1]?.pinned)

                            return (
                                <>
                                    <SortableSceneTab
                                        key={sortableId}
                                        tab={tab}
                                        index={index}
                                        sortableId={sortableId}
                                        onConfigurePinnedTabs={() => setIsConfigurePinnedTabsOpen(true)}
                                    />
                                    {isLastPinned && (
                                        <div
                                            className="h-4 w-px bg-border-secondary shrink-0 rounded opacity-50"
                                            aria-hidden="true"
                                        />
                                    )}
                                </>
                            )
                        })}
                    </ScrollableShadows>
                    <AppShortcut name="NewTab" keybind={[keyBinds.newTab]} intent="New tab" interaction="click">
                        <Link
                            to={urls.newTab()}
                            data-attr="scene-tab-new-button"
                            onClick={(e) => {
                                e.preventDefault()
                                newTab()
                            }}
                            tooltip="New tab"
                            tooltipCloseDelayMs={0}
                            buttonProps={{
                                size: 'sm',
                                className:
                                    'p-1 flex flex-row items-center gap-1 cursor-pointer rounded border-b z-20 ml-1',
                                iconOnly: true,
                            }}
                        >
                            <IconPlus className="!ml-0" fontSize={14} />
                        </Link>
                    </AppShortcut>
                </SortableContext>
            </DndContext>
            <ConfigurePinnedTabsModal
                isOpen={isConfigurePinnedTabsOpen}
                onClose={() => setIsConfigurePinnedTabsOpen(false)}
            />
        </div>
    )
}

const getSortableId = (tab: SceneTab, index: number): string => `${tab.id}-${index}`

interface SortableSceneTabProps {
    tab: SceneTab
    index: number
    sortableId: string
    containerClassName?: string
    onConfigurePinnedTabs: () => void
}

function SortableSceneTab({
    tab,
    index,
    sortableId,
    containerClassName,
    onConfigurePinnedTabs,
}: SortableSceneTabProps): JSX.Element {
    const { setNodeRef, attributes, listeners, transform, transition, isDragging } = useSortable({
        id: sortableId,
        data: { index },
    })
    const style: React.CSSProperties = {
        transform: CSS.Translate.toString(transform),
        transition,
        opacity: isDragging ? 0.5 : undefined,
    }

    const isPinned = !!tab.pinned

    return (
        <div
            ref={setNodeRef}
            style={style}
            {...attributes}
            {...listeners}
            className={cn(isPinned ? 'w-[var(--button-height-sm)] shrink-0' : 'flex-1 min-w-[100px]')}
        >
            <SceneTabContextMenu tab={tab} onConfigurePinnedTabs={onConfigurePinnedTabs}>
                <SceneTabComponent
                    tab={tab}
                    isDragging={isDragging}
                    containerClassName={containerClassName}
                    index={index}
                />
            </SceneTabContextMenu>
        </div>
    )
}

interface SceneTabProps {
    tab: SceneTab
    className?: string
    isDragging?: boolean
    containerClassName?: string
    index: number
}

function SceneTabComponent({ tab, className, isDragging, containerClassName }: SceneTabProps): JSX.Element {
    const inputRef = useRef<HTMLInputElement>(null)
    const isPinned = !!tab.pinned
    const canRemoveTab = !isPinned
    const { clickOnTab, removeTab, startTabEdit, endTabEdit, saveTabEdit } = useActions(sceneLogic)
    const { editingTabId } = useValues(sceneLogic)
    const [editValue, setEditValue] = useState('')
    const isEditing = editingTabId === tab.id

    useEffect(() => {
        if (isEditing && editValue === '') {
            setEditValue(tab.customTitle || tab.title)
        }
    }, [isEditing, tab.customTitle, tab.title, editValue])

    useEffect(() => {
        if (isEditing && inputRef.current) {
            // focus the input with delay to ensure the tab input is rendered
            setTimeout(() => {
                inputRef.current?.focus()
            }, 100)
        }
    }, [isEditing])

    return (
        <div className={cn('relative w-full', containerClassName)}>
            <ButtonGroupPrimitive
                fullWidth
                size="sm"
                className="group border-0 rounded-none group/colorful-product-icons colorful-product-icons-true"
            >
                {canRemoveTab && (
                    <AppShortcut
                        name="CloseActiveTab"
                        keybind={[keyBinds.closeActiveTab]}
                        intent="Close active tab"
                        interaction="click"
                        disabled={!tab.active}
                    >
                        <ButtonPrimitive
                            onClick={(e) => {
                                e.stopPropagation()
                                e.preventDefault()
                                removeTab(tab)
                            }}
                            tooltip={!tab.active ? 'Close tab' : 'Close active tab'}
                            tooltipCloseDelayMs={0}
                            isSideActionRight
                            iconOnly
                            size="xs"
                            className="group-hover:opacity-100 opacity-0 order-last group z-20 size-5 rounded top-1/2 -translate-y-1/2 right-[5px] hover:[&~.button-primitive:not(.tab-active)]:bg-surface-primary"
                        >
                            <IconX className="text-tertiary size-3 group-hover:text-primary z-10" />
                        </ButtonPrimitive>
                    </AppShortcut>
                )}
                <ButtonPrimitive
                    onClick={(e) => {
                        e.stopPropagation()
                        e.preventDefault()
                        if (!isDragging) {
                            clickOnTab(tab)
                            router.actions.push(`${tab.pathname}${tab.search}${tab.hash}`)
                        }
                    }}
                    onAuxClick={(e) => {
                        e.stopPropagation()
                        e.preventDefault()
                        if (e.button === 1 && !isDragging && canRemoveTab) {
                            removeTab(tab)
                        }
                    }}
                    onDoubleClick={(e) => {
                        e.stopPropagation()
                        e.preventDefault()
                        if (!isDragging && !isEditing) {
                            startTabEdit(tab)
                            setEditValue(tab.customTitle || tab.title)
                        }
                    }}
                    forceVariant={true}
                    variant={tab.active ? 'panel' : 'default'}
                    hasSideActionRight
                    className={cn(
                        'w-full order-first',
                        'relative pb-0.5 pt-[2px] pl-2 pr-5 flex flex-row items-center gap-1 border border-transparent text-tertiary',
                        tab.active
                            ? 'tab-active cursor-default text-primary hover:bg-[var(--color-bg-fill-button-panel)]'
                            : 'cursor-pointer hover:text-primary z-20',
                        'focus:outline-none',
                        isPinned && 'scene-tab--pinned justify-center pl-1 pr-1 gap-0',
                        className
                    )}
                    tooltip={
                        tab.customTitle && tab.customTitle !== 'Search'
                            ? `${tab.customTitle} (${tab.title})`
                            : tab.title
                    }
                    tooltipPlacement="bottom"
                    aria-label={isPinned ? tab.customTitle || tab.title : undefined}
                >
                    {tab.iconType === 'blank' ? (
                        <></>
                    ) : tab.iconType === 'loading' ? (
                        <Spinner />
                    ) : (
                        iconForType(tab.iconType as FileSystemIconType)
                    )}
                    {isPinned ? (
                        <span className="sr-only">{tab.customTitle || tab.title}</span>
                    ) : isEditing ? (
                        <input
                            ref={inputRef}
                            className="scene-tab-title grow text-left bg-primary outline-1 text-primary z-30 max-w-full input-like"
                            value={editValue}
                            onChange={(e) => setEditValue(e.target.value)}
                            onBlur={() => {
                                saveTabEdit(tab, editValue)
                                endTabEdit()
                            }}
                            onKeyDown={(e) => {
                                if (e.key === 'Escape') {
                                    endTabEdit()
                                    setEditValue('')
                                } else if (e.key === 'Enter') {
                                    saveTabEdit(tab, editValue)
                                    endTabEdit()
                                }
                            }}
                            autoComplete="off"
                            autoFocus
                            onFocus={(e) => e.target.select()}
                        />
                    ) : (
                        <div
                            className={cn('scene-tab-title flex-grow text-left truncate', tab.customTitle && 'italic')}
                        >
                            {tab.customTitle || tab.title}
                        </div>
                    )}
                </ButtonPrimitive>
            </ButtonGroupPrimitive>
        </div>
    )
}
