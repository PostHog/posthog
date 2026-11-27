import { ReactNode } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

interface ListEmptyStateActionBase {
    label: string
    icon?: JSX.Element
    'data-attr': string
}

/** A button that runs `onClick`, or a link to `to`, so that a step to another page opens like any link. */
export type ListEmptyStateAction = ListEmptyStateActionBase &
    ({ onClick: () => void; to?: never } | { to: string; onClick?: never })

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
                    to={action.to}
                    data-attr={action['data-attr']}
                >
                    {action.label}
                </LemonButton>
            ) : null}
        </div>
    )
}
