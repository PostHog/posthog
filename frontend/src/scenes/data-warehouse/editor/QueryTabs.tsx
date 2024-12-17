import { IconPlus, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'

import { QueryTab } from './multitabEditorLogic'

interface QueryTabsProps {
    models: QueryTab[]
    onClick: (model: QueryTab) => void
    onClear: (model: QueryTab) => void
    onAdd: () => void
    activeModelUri: QueryTab | null
}

export function QueryTabs({ models, onClear, onClick, onAdd, activeModelUri }: QueryTabsProps): JSX.Element {
    return (
        <div className="flex flex-row w-full overflow-scroll hide-scrollbar h-10">
            {models.map((model: QueryTab) => (
                <QueryTabComponent
                    key={model.uri.path}
                    model={model}
                    onClear={models.length > 1 ? onClear : undefined}
                    onClick={onClick}
                    active={activeModelUri?.uri.path === model.uri.path}
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
}

function QueryTabComponent({ model, active, onClear, onClick }: QueryTabProps): JSX.Element {
    return (
        <button
            onClick={() => onClick?.(model)}
            className={clsx(
                'space-y-px rounded-t p-1 flex flex-row items-center gap-1 hover:bg-[var(--bg-light)] cursor-pointer',
                active ? 'bg-[var(--bg-light)] border' : 'bg-[var(--background-primary)]',
                onClear ? 'pl-3 pr-2' : 'px-3'
            )}
        >
            {model.view?.name ?? 'Untitled'}
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
        </button>
    )
}
