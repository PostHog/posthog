import { IconRefresh, IconWarning } from '@posthog/icons'

import { ListEmptyState } from './ListEmptyState'

export interface ListErrorStateProps {
    title: string
    description: string
    retry?: { onClick: () => void; 'data-attr': string }
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
