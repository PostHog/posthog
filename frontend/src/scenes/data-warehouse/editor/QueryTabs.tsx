import clsx from 'clsx'
import { useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconPlus, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import AutoTab from './AutoTab'
import { NEW_QUERY, QueryTab, multitabEditorLogic } from './multitabEditorLogic'

interface QueryTabsProps {
    models: QueryTab[]
    onClick: (model: QueryTab) => void
    onClear: (model: QueryTab) => void
    onRename: (model: QueryTab, newName: string) => void
    onAdd: () => void
    activeModelUri: QueryTab | null
}

export function QueryTabs({ models, onClear, onClick, onAdd, onRename, activeModelUri }: QueryTabsProps): JSX.Element {
    const { allTabs } = useValues(multitabEditorLogic)
    const containerRef = useRef<HTMLDivElement | null>(null)
    const prevTabsCountRef = useRef(allTabs.length)

    useEffect(() => {
        if (allTabs.length > prevTabsCountRef.current) {
            containerRef.current?.scrollTo({
                left: containerRef.current.scrollWidth,
                behavior: 'smooth',
            })
        }

        prevTabsCountRef.current = allTabs.length
    }, [allTabs])

    return (
        <>
            <div
                // height is hardcoded to match implicit height from tree view nav bar
                className="hide-scrollbar flex h-[39px] flex-row overflow-auto"
                ref={containerRef}
            >
                {models.map((model: QueryTab) => (
                    <QueryTabComponent
                        key={model.uri.path}
                        model={model}
                        onClear={models.length > 1 ? onClear : undefined}
                        onClick={onClick}
                        active={activeModelUri?.uri.path === model.uri.path}
                        onRename={onRename}
                    />
                ))}
            </div>
            <LemonButton
                className="rounded-none"
                onClick={() => onAdd()}
                icon={<IconPlus fontSize={14} />}
                data-attr="sql-editor-new-tab-button"
            />
        </>
    )
}

interface QueryTabProps {
    model: QueryTab
    onClick: (model: QueryTab) => void
    onClear?: (model: QueryTab) => void
    active: boolean
    onRename: (model: QueryTab, newName: string) => void
}

function QueryTabComponent({ model, active, onClear, onClick, onRename }: QueryTabProps): JSX.Element {
    const [tabName, setTabName] = useState(() => model.name || NEW_QUERY)
    const [isEditing, setIsEditing] = useState(false)

    useEffect(() => {
        setTabName(model.view?.name || model.name || NEW_QUERY)
    }, [model.view?.name, model.name])

    const handleRename = (): void => {
        setIsEditing(false)
        onRename(model, tabName)
    }

    return (
        <div
            onClick={() => onClick?.(model)}
            className={clsx(
                'deprecated-space-y-px hover:bg-surface-primary flex cursor-pointer flex-row items-center gap-1 border-b-2 p-1',
                active
                    ? 'bg-surface-primary !border-brand-yellow border-b-2'
                    : 'bg-surface-secondary border-transparent',
                onClear ? 'pl-3 pr-2' : 'px-3'
            )}
        >
            {isEditing ? (
                <AutoTab
                    value={tabName}
                    onChange={(e) => setTabName(e.target.value)}
                    onBlur={handleRename}
                    autoFocus
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            handleRename()
                        } else if (e.key === 'Escape') {
                            setIsEditing(false)
                        }
                    }}
                />
            ) : (
                <div
                    onDoubleClick={() => {
                        // disable editing views
                        if (model.view) {
                            return
                        }
                        setIsEditing(!isEditing)
                    }}
                    className="flex-grow whitespace-pre text-left"
                >
                    {tabName}
                </div>
            )}
            {onClear && (
                <LemonButton
                    onClick={(e) => {
                        e.stopPropagation()
                        onClear(model)
                    }}
                    size="xsmall"
                    icon={<IconX />}
                />
            )}
        </div>
    )
}
