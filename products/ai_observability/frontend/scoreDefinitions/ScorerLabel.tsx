import { LemonTag } from '@posthog/lemon-ui'

import type { OfflineScorerVersionReadApi } from '../generated/api.schemas'

export function ScorerLabel({
    scorer,
}: {
    scorer: Pick<OfflineScorerVersionReadApi, 'name' | 'short_name' | 'version'>
}): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-1 min-w-0 normal-case">
            <span className="whitespace-normal break-words min-w-0 max-w-full">{scorer.short_name || scorer.name}</span>
            <LemonTag type="muted" size="small" className="shrink-0" weight="normal">
                {`v${scorer.version}`}
            </LemonTag>
        </div>
    )
}
