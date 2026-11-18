import { LemonButton } from '@posthog/lemon-ui'

import { HEALTH_ISSUES_PAGE_SIZE } from '../types'

export function HealthShowMoreFooter({
    shown,
    total,
    loading,
    onShowMore,
}: {
    shown: number
    total: number
    loading: boolean
    onShowMore: () => void
}): JSX.Element | null {
    if (shown >= total) {
        return null
    }
    return (
        <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-muted">
                Showing {shown} of {total}
            </span>
            <LemonButton type="secondary" size="small" loading={loading} onClick={onShowMore}>
                Show {Math.min(HEALTH_ISSUES_PAGE_SIZE, total - shown)} more
            </LemonButton>
        </div>
    )
}
