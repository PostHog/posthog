import { Button } from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import type { SelectedRecordingsBarProps } from './SelectedRecordingsBar'

export function QuillSelectedRecordingsBar({ count, loading, onShowAll }: SelectedRecordingsBarProps): JSX.Element {
    return (
        <div
            data-quill
            className="mb-2 flex items-center justify-between gap-2 rounded border border-border bg-muted px-2 py-1 text-foreground"
        >
            <span className="min-w-0 truncate text-xs text-muted-foreground">
                Showing {pluralize(count, 'selected recording')}
            </span>
            <Button
                size="xs"
                className="shrink-0"
                onClick={onShowAll}
                loading={loading}
                data-attr="list-clear-session-ids"
            >
                Show all
            </Button>
        </div>
    )
}
