import { IconPlus, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useEffect, useState } from 'react'

import AutoTab from './AutoTab'
import { NEW_QUERY, QueryTab } from './multitabEditorLogic'

interface QueryTabsProps {
    models: QueryTab[]
    onClick: (model: QueryTab) => void
    onClear: (model: QueryTab) => void
    onRename: (model: QueryTab, newName: string) => void
    onAdd: () => void
    activeModelUri: QueryTab | null
}

export function QueryTabs({ models, onClear, onClick, onAdd, onRename, activeModelUri }: QueryTabsProps): JSX.Element {
    return (
        <div className="flex flex-row w-full overflow-scroll hide-scrollbar h-10">
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
            <LemonButton className="rounded-none" onClick={() => onAdd()} icon={<IconPlus fontSize={14} />} />
        </div>
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
    }, [model.view?.name])

    const handleRename = (): void => {
        setIsEditing(false)
        onRename(model, tabName)
    }

    return (
        <div
            onClick={() => onClick?.(model)}
            className={clsx(
                'deprecated-space-y-px p-1 flex border-b-2 flex-row items-center gap-1 hover:bg-surface-primary cursor-pointer',
                active
                    ? 'bg-surface-primary border-b-2 !border-brand-yellow'
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
                    handleRename={() => onRename(model, tabName)}
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
                    className="flex-grow text-left whitespace-pre"
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
