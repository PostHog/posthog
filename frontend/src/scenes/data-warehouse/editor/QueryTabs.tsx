import { IconPlus, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { Uri } from 'monaco-editor'

interface QueryTabsProps {
    models: Uri[]
    onClick: (model: Uri) => void
    onClear: (model: Uri) => void
    onAdd: () => void
    activeModelUri: Uri | null
}

export function QueryTabs({ models, onClear, onClick, onAdd, activeModelUri }: QueryTabsProps): JSX.Element {
    return (
        <div className="flex flex-row overflow-scroll hide-scrollbar">
            {models.map((model: Uri) => (
                <QueryTab
                    key={model.path}
                    model={model}
                    onClear={models.length > 1 ? onClear : undefined}
                    onClick={onClick}
                    active={activeModelUri?.path === model.path}
                />
            ))}
            <LemonButton onClick={onAdd} icon={<IconPlus fontSize={14} />} />
        </div>
    )
}

interface QueryTabProps {
    model: Uri
    onClick: (model: Uri) => void
    onClear?: (model: Uri) => void
    active: boolean
}

function QueryTab({ model, active, onClear, onClick }: QueryTabProps): JSX.Element {
    return (
        <button
            onClick={() => onClick?.(model)}
            className={clsx(
                'space-y-px rounded-t p-1 flex flex-row items-center gap-1 hover:bg-[var(--bg-light)] cursor-pointer',
                active ? 'bg-[var(--bg-light)] border' : 'bg-bg-3000',
                onClear ? 'pl-3 pr-2' : 'px-3'
            )}
        >
            Untitled
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
