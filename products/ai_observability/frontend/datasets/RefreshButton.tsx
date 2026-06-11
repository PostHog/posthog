import { IconRefresh } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'

export interface RefreshButtonProps {
    onClick: () => void
    isRefreshing: boolean
}

export function RefreshButton({ onClick, isRefreshing }: RefreshButtonProps): JSX.Element {
    return (
        <div className="relative">
            <LemonButton
                onClick={onClick}
                type="secondary"
                icon={isRefreshing ? <Spinner textColored /> : <IconRefresh />}
                size="small"
                disabledReason={isRefreshing ? 'Refreshing...' : undefined}
            >
                <span>{isRefreshing ? 'Refreshing...' : 'Refresh'}</span>
            </LemonButton>
        </div>
    )
}
