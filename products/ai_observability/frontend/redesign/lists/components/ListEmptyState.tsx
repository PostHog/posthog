import { ReactNode } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

export interface ListEmptyStateAction {
    label: string
    onClick: () => void
    icon?: JSX.Element
    'data-attr': string
}

export interface ListEmptyStateProps {
    title: string
    description: string
    icon?: ReactNode
    action?: ListEmptyStateAction
}

export function ListEmptyState({ title, description, icon, action }: ListEmptyStateProps): JSX.Element {
    return (
        <div className="flex flex-col items-center gap-2 py-8 text-center">
            <h3 className="m-0 flex items-center gap-1 text-sm font-semibold text-primary">
                {icon}
                <span>{title}</span>
            </h3>
            <p className="m-0 max-w-120 text-secondary">{description}</p>
            {action ? (
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={action.icon}
                    onClick={action.onClick}
                    data-attr={action['data-attr']}
                >
                    {action.label}
                </LemonButton>
            ) : null}
        </div>
    )
}
