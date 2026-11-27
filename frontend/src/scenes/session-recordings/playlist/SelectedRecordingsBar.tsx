import { LemonButton } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

export interface SelectedRecordingsBarProps {
    count: number
    loading: boolean
    onShowAll: () => void
}

export function SelectedRecordingsBar({ count, loading, onShowAll }: SelectedRecordingsBarProps): JSX.Element {
    return (
        <div className="mb-2 flex items-center justify-between gap-2 rounded border bg-fill-primary px-2 py-1">
            <span className="min-w-0 truncate text-xs text-secondary">
                Showing {pluralize(count, 'selected recording')}
            </span>
            <LemonButton
                data-attr="list-clear-session-ids"
                className="shrink-0"
                size="xsmall"
                type="tertiary"
                onClick={onShowAll}
                loading={loading}
            >
                Show all
            </LemonButton>
        </div>
    )
}
