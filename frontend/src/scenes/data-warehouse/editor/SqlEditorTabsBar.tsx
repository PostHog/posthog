import './SqlEditorTabsBar.css'

import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconPlus, IconX } from '@posthog/icons'

import { Link } from 'lib/lemon-ui/Link'
import { ButtonGroupPrimitive, ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { sqlEditorTabsLogic, type SqlEditorTab } from './sqlEditorTabsLogic'

export function SqlEditorTabsBar(): JSX.Element {
    const { tabs, activeTabId } = useValues(sqlEditorTabsLogic)
    const { addTab } = useActions(sqlEditorTabsLogic)

    return (
        <div className="h-[var(--scene-layout-header-height)] flex items-center w-full min-w-0 bg-surface-tertiary z-[var(--z-top-navigation)] relative">
            {/* Line below tabs to complete border on the editor below */}
            <div className="absolute bottom-0 w-full px-[5px] lg:pr-2">
                <div className="w-full bottom-0 h-px border-b border-primary z-10" />
            </div>

            <div className="gap-1 flex-1 min-w-0 items-center flex h-[var(--scene-layout-header-height)] lg:h-auto pr-2 pl-1">
                {tabs.map((tab, index) => (
                    <div key={tab.id} data-tab-id={tab.id} className="w-full flex-1 min-w-[100px] max-w-[250px]">
                        <SqlEditorTab tab={tab} index={index} isActive={tab.id === activeTabId} />
                    </div>
                ))}
                <Link
                    to="#"
                    data-attr="sql-editor-new-tab"
                    onClick={(e) => {
                        e.preventDefault()
                        addTab()
                    }}
                    tooltip="New SQL editor tab — queries in other tabs keep running"
                    tooltipCloseDelayMs={0}
                    buttonProps={{
                        iconOnly: true,
                        className: 'p-1 flex items-center gap-1 cursor-pointer rounded border-b z-20',
                    }}
                >
                    <IconPlus className="!ml-0 size-3" />
                </Link>
            </div>
        </div>
    )
}

interface SqlEditorTabProps {
    tab: SqlEditorTab
    index: number
    isActive: boolean
}

function SqlEditorTab({ tab, index, isActive }: SqlEditorTabProps): JSX.Element {
    const { tabs } = useValues(sqlEditorTabsLogic)
    const { setActiveTab, closeTab, renameTab } = useActions(sqlEditorTabsLogic)
    const [isEditing, setIsEditing] = useState(false)
    const [editValue, setEditValue] = useState(tab.label)
    const inputRef = useRef<HTMLInputElement>(null)

    const canRemove = tabs.length > 1
    const firstTabActive = index === 0 && isActive

    useEffect(() => {
        if (isEditing) {
            setEditValue(tab.label)
            setTimeout(() => inputRef.current?.focus(), 50)
        }
        // Intentionally omit tab.label: resetting editValue on every external
        // label change would discard the user's in-progress rename input.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isEditing])

    const commit = (): void => {
        const trimmed = editValue.trim()
        if (trimmed && trimmed !== tab.label) {
            renameTab(tab.id, trimmed)
        }
        setIsEditing(false)
    }

    return (
        <div className="relative w-full">
            <ButtonGroupPrimitive
                fullWidth
                size="sm"
                className="group border-0 rounded-none group/colorful-product-icons colorful-product-icons-true"
            >
                {canRemove && (
                    <ButtonPrimitive
                        onClick={(e) => {
                            e.stopPropagation()
                            e.preventDefault()
                            closeTab(tab.id)
                        }}
                        tooltip={isActive ? 'Close active tab' : 'Close tab'}
                        tooltipCloseDelayMs={0}
                        isSideActionRight
                        iconOnly
                        size="xs"
                        className="order-last group z-20 size-5 rounded top-1/2 -translate-y-1/2 right-[5px] hover:[&~.button-primitive:not(.tab-active)]:bg-surface-primary"
                    >
                        <IconX className="text-tertiary size-3 group-hover:text-primary z-10" />
                    </ButtonPrimitive>
                )}
                <ButtonPrimitive
                    onClick={(e) => {
                        e.stopPropagation()
                        e.preventDefault()
                        if (!isActive) {
                            setActiveTab(tab.id)
                        }
                    }}
                    onAuxClick={(e) => {
                        e.stopPropagation()
                        e.preventDefault()
                        if (e.button === 1 && canRemove) {
                            closeTab(tab.id)
                        }
                    }}
                    onDoubleClick={(e) => {
                        e.stopPropagation()
                        e.preventDefault()
                        if (!isEditing) {
                            setIsEditing(true)
                        }
                    }}
                    forceVariant={true}
                    variant="default"
                    hasSideActionRight
                    className={cn(
                        'w-full order-first min-w-0',
                        'relative pb-0.5 pt-[2px] pl-2 pr-5 flex flex-row items-center gap-1 border border-transparent text-tertiary',
                        isActive
                            ? 'tab-active bg-[var(--scene-layout-background)] cursor-default text-primary border-primary lg:rounded-b-none'
                            : 'cursor-pointer hover:text-primary z-20',
                        firstTabActive && 'lg:rounded-bl-none',
                        'focus:outline-none'
                    )}
                    tooltip={tab.label}
                    tooltipPlacement="bottom"
                >
                    <span className="relative">{iconForType('sql_editor')}</span>

                    {isEditing ? (
                        <input
                            ref={inputRef}
                            className="scene-tab-title grow text-left bg-primary outline-1 text-primary z-30 max-w-full input-like"
                            value={editValue}
                            onChange={(e) => setEditValue(e.target.value)}
                            onBlur={commit}
                            onKeyDown={(e) => {
                                if (e.key === 'Escape') {
                                    setIsEditing(false)
                                } else if (e.key === 'Enter') {
                                    commit()
                                }
                            }}
                            autoComplete="off"
                            autoFocus
                            onFocus={(e) => e.target.select()}
                        />
                    ) : (
                        <div className="scene-tab-title text-left truncate min-w-0">{tab.label}</div>
                    )}
                </ButtonPrimitive>
            </ButtonGroupPrimitive>
            {isActive && (
                <div
                    className={cn(
                        'scene-tab-active-indicator hidden lg:block',
                        index === 0 && 'scene-tab-active-indicator--first',
                        firstTabActive && 'scene-tab-indicator--active-first'
                    )}
                />
            )}
        </div>
    )
}
