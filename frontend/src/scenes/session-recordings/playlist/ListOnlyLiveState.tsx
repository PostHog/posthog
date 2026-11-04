import { LemonButton } from '@posthog/lemon-ui'

export interface ListOnlyLiveStateProps {
    hasNext: boolean
    loading: boolean
    onLoadOlder: () => void
}

export function ListOnlyLiveState({ hasNext, loading, onLoadOlder }: ListOnlyLiveStateProps): JSX.Element {
    return (
        <div className="flex flex-col items-center gap-2 p-4 text-secondary text-sm">
            <span>Only live recordings so far</span>
            {hasNext && (
                <LemonButton
                    type="secondary"
                    size="small"
                    loading={loading}
                    onClick={onLoadOlder}
                    data-attr="list-load-older"
                >
                    Load more
                </LemonButton>
            )}
        </div>
    )
}
