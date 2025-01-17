import { IconPlus, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useState } from 'react'

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
        <div className="flex flex-row w-full overflow-scroll hide-scrollbar h-10 pt-1">
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
            <LemonButton onClick={() => onAdd()} icon={<IconPlus fontSize={14} />} />
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

    const handleRename = (): void => {
        setIsEditing(false)
        onRename(model, tabName)
    }

    return (
        <div
            onClick={() => onClick?.(model)}
            className={clsx(
                'space-y-px rounded-t p-1 flex flex-row items-center gap-1 hover:bg-[var(--bg-light)] cursor-pointer',
                active ? 'bg-[var(--bg-light)] border-t border-l border-r' : 'bg-bg-3000',
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
                <div onDoubleClick={() => setIsEditing(!isEditing)} className="flex-grow text-left whitespace-pre">
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
