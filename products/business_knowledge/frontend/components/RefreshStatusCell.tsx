import { LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { KnowledgeSource } from '../scenes/businessKnowledgeLogic'

export function RefreshStatusCell({ source }: { source: KnowledgeSource }): JSX.Element | null {
    if (source.source_type !== 'url') {
        return null
    }
    if (!source.last_refresh_at) {
        return <span className="text-muted">—</span>
    }
    return (
        <div className="flex flex-col gap-0.5">
            <TZLabel time={source.last_refresh_at} />
            {source.last_refresh_status === 'error' ? (
                <LemonTag type="danger" title={source.last_refresh_error || undefined}>
                    refresh failed
                </LemonTag>
            ) : null}
            {source.next_refresh_at ? (
                <span className="text-xs text-muted">
                    next <TZLabel time={source.next_refresh_at} />
                </span>
            ) : null}
        </div>
    )
}
