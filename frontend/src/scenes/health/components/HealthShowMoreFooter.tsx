import { LemonButton } from '@posthog/lemon-ui'

import { HEALTH_ISSUES_PAGE_SIZE } from '../types'

export function HealthShowMoreFooter({
    shown,
    total,
    remaining,
    loading,
    onShowMore,
}: {
    shown: number
    total: number
    remaining: number
    loading: boolean
    onShowMore: () => void
}): JSX.Element | null {
    if (remaining <= 0) {
        return null
    }
    return (
        <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-muted">
                <span>Showing&nbsp;</span>
                <span translate="no">{shown}</span>
                <span>&nbsp;of&nbsp;</span>
                <span translate="no">{total}</span>
            </span>
            <LemonButton type="secondary" size="small" loading={loading} onClick={onShowMore}>
                <span>Show&nbsp;</span>
                <span translate="no">{Math.min(HEALTH_ISSUES_PAGE_SIZE, remaining)}</span>
                <span>&nbsp;more</span>
            </LemonButton>
        </div>
    )
}
