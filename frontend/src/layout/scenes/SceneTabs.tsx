import '~/layout/scenes/SceneTabs.css'

import { DndContext, DragEndEvent, PointerSensor, useSensor, useSensors } from '@dnd-kit/core'
import { SortableContext, horizontalListSortingStrategy, useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import React, { useEffect, useRef, useState } from 'react'

import { IconPlus, IconSearch, IconX } from '@posthog/icons'

import { commandBarLogic } from 'lib/components/CommandBar/commandBarLogic'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { IconMenu } from 'lib/lemon-ui/icons'
import { ButtonGroupPrimitive, ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'
import { SceneTab } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { SceneTabContextMenu } from '~/layout/scenes/SceneTabContextMenu'
import { FileSystemIconType } from '~/queries/schema/schema-general'
import { sceneLogic } from '~/scenes/sceneLogic'

import { navigationLogic } from '../navigation/navigationLogic'
import { panelLayoutLogic } from '../panel-layout/panelLayoutLogic'

export interface SceneTabsProps {
    className?: string
}

export function SceneTabs({ className }: SceneTabsProps): JSX.Element {
    const { tabs } = useValues(sceneLogic)
    const { newTab, reorderTabs } = useActions(sceneLogic)
    const { toggleSearchBar } = useActions(commandBarLogic)
    const { isLayoutPanelVisible } = useValues(panelLayoutLogic)
    const { mobileLayout } = useValues(navigationLogic)
    const { showLayoutNavBar } = useActions(panelLayoutLogic)
    const { isLayoutNavbarVisibleForMobile } = useValues(panelLayoutLogic)
    const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }))

    const handleDragEnd = ({ active, over }: DragEndEvent): void => {
        if (over && active.id !== over.id) {
            reorderTabs(active.id as string, over.id as string)
        }
    }

    return (
        <div
            className={cn(
                'h-[var(--scene-layout-header-height)] flex items-center w-full bg-surface-tertiary z-[var(--z-top-navigation)] pr-1.5 border-b border-primary relative',
                className
            )}
        >
            {/* rounded corner on the left to make scene curve into tab line */}
            {mobileLayout && (
                <ButtonPrimitive
                    onClick={() => showLayoutNavBar(!isLayoutNavbarVisibleForMobile)}
                    iconOnly
                    className="ml-1"
                >
                    {isLayoutNavbarVisibleForMobile ? <IconX /> : <IconMenu />}
                </ButtonPrimitive>
            )}

            {/* rounded corner on the left to make scene curve into tab line */}
            {!isLayoutPanelVisible && (
                <div className="absolute left-0 -bottom-1 size-2 bg-surface-tertiary">
                    <div className="relative -bottom-1 size-2 border-l border-t border-primary rounded-tl bg-[var(--scene-layout-background)]" />
                </div>
            )}

            <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
                <SortableContext items={[...tabs.map((t) => t.id), 'new']} strategy={horizontalListSortingStrategy}>
                    <div className={cn('flex flex-row gap-1 max-w-full items-center', className)}>
                        <div className="pl-[2px] shrink-0">
                            <ButtonPrimitive
                                iconOnly
                                onClick={toggleSearchBar}
                                data-attr="tree-navbar-search-button"
                                size="sm"
                                aria-label="Search (Command + K) or Commands (Command + Shift + K)"
                                aria-describedby="search-tooltip"
                                tooltip={
                                    <div className="flex flex-col gap-0.5" id="search-tooltip">
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
                        <div
                            className="scene-tab-row grid min-w-0 gap-1 items-center h-[36px]"
                            style={{
                                gridTemplateColumns:
                                    tabs.length === 1
                                        ? '250px'
                                        : tabs.length === 2
                                          ? 'repeat(2, 250px)'
                                          : `repeat(${tabs.length}, minmax(40px, 250px))`,
                            }}
                        >
                            {tabs.map((tab) => (
                                <SortableSceneTab key={tab.id} tab={tab} />
                            ))}
                        </div>
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
    const inputRef = useRef<HTMLInputElement>(null)
    const canRemoveTab = true
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
            setTimeout(() => {
                inputRef.current?.focus()
            }, 100)
        }
    }, [isEditing])

    return (
        <div className="relative">
            <div
                className={cn({
                    'scene-tab-active-indicator': tab.active,
                })}
            />

            <ButtonGroupPrimitive groupVariant="default" fullWidth className="border-0 rounded-none">
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
                        if (e.button === 1 && !isDragging) {
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
                    hasSideActionRight
                    className={cn(
                        'w-full',
                        'relative p-0.5 flex flex-row items-center gap-1 rounded-tr rounded-tl border border-transparent',
                        tab.active
                            ? 'rounded-bl-none rounded-br-none cursor-default text-primary bg-primary border-primary'
                            : 'cursor-pointer text-secondary bg-transparent hover:bg-surface-primary hover:text-primary-hover z-20',
                        canRemoveTab ? 'pl-2 pr-1' : 'px-3',
                        'focus:outline-none',
                        className
                    )}
                    tooltip={
                        tab.customTitle && tab.customTitle !== 'New tab'
                            ? `${tab.customTitle} (${tab.title})`
                            : tab.title
                    }
                >
                    {tab.iconType === 'blank' ? (
                        <></>
                    ) : tab.iconType === 'loading' ? (
                        <Spinner />
                    ) : (
                        iconForType(tab.iconType as FileSystemIconType)
                    )}
                    {isEditing ? (
                        <input
                            ref={inputRef}
                            className="scene-tab-title flex-grow text-left bg-primary border-none outline-1 text-primary z-10"
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
                {canRemoveTab && (
                    <ButtonPrimitive
                        onClick={(e) => {
                            e.stopPropagation()
                            e.preventDefault()
                            removeTab(tab)
                        }}
                        isSideActionRight
                        iconOnly
                        size="xs"
                        className="group hover:bg-transparent mt-px z-20"
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
                        <IconX className="text-tertiary size-3 group-hover:text-primary z-10" />
                    </ButtonPrimitive>
                )}
            </ButtonGroupPrimitive>
        </div>
    )
}
