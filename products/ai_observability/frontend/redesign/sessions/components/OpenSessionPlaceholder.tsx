import { ListEmptyState } from '../../lists/components/ListEmptyState'
import { ListErrorState } from '../../lists/components/ListErrorState'
import type { LoadFailure } from '../../trace/types'

// pinned: autocapture dashboards and tests select these controls by their values
const CLOSE_DATA_ATTR = 'ai-observability-sessions-list-close-session'
const RETRY_DATA_ATTR = 'ai-observability-sessions-list-retry-session'

export interface OpenSessionPlaceholderProps {
    status: 'none' | LoadFailure
    onRetry: () => void
    onClose: () => void
}

/** The pane of the sessions list while there is no open session to show the conversation of. */
export function OpenSessionPlaceholder({ status, onRetry, onClose }: OpenSessionPlaceholderProps): JSX.Element {
    if (status === 'not_found') {
        return (
            <ListEmptyState
                title="Session not found"
                description="Check the link, or pick a session from the list."
                action={{ label: 'Clear selection', onClick: onClose, 'data-attr': CLOSE_DATA_ATTR }}
            />
        )
    }
    if (status === 'failed') {
        return (
            <ListErrorState
                title="Couldn't load this session"
                description="Try again. If it keeps happening, contact support."
                retry={{ onClick: onRetry, 'data-attr': RETRY_DATA_ATTR }}
            />
        )
    }
    return (
        <ListEmptyState title="No session open" description="Pick a session from the list to read its conversation." />
    )
}
