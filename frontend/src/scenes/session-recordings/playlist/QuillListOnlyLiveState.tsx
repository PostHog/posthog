import { Button } from '@posthog/quill'

import type { ListOnlyLiveStateProps } from './ListOnlyLiveState'

export function QuillListOnlyLiveState({ hasNext, loading, onLoadOlder }: ListOnlyLiveStateProps): JSX.Element {
    return (
        <div data-quill className="flex flex-col items-center gap-2 p-4 text-sm text-muted-foreground">
            <span>Only live recordings so far</span>
            {hasNext && (
                <Button variant="outline" size="sm" loading={loading} onClick={onLoadOlder} data-attr="list-load-older">
                    Load more
                </Button>
            )}
        </div>
    )
}
