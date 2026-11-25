import { IconRefresh, IconWarning } from '@posthog/icons'

import { ListEmptyState, ListEmptyStateAction } from './ListEmptyState'

export interface ListErrorStateProps {
    title: string
    description: string
    retry?: Pick<ListEmptyStateAction, 'onClick' | 'data-attr'>
}

export function ListErrorState({ title, description, retry }: ListErrorStateProps): JSX.Element {
    return (
        <ListEmptyState
            title={title}
            description={description}
            icon={<IconWarning className="text-danger" />}
            action={retry ? { ...retry, label: 'Retry', icon: <IconRefresh /> } : undefined}
        />
    )
}
