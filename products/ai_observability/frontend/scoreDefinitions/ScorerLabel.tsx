import { LemonTag, Link } from '@posthog/lemon-ui'

import type { OfflineScorerVersionReadApi } from '../generated/api.schemas'

export function ScorerLabel({
    scorer,
    historyLink,
}: {
    scorer: Pick<OfflineScorerVersionReadApi, 'name' | 'version'> &
        Partial<Pick<OfflineScorerVersionReadApi, 'short_name'>>
    historyLink?: { to: string; 'data-attr': string }
}): JSX.Element {
    const name = scorer.short_name || scorer.name
    return (
        <div className="flex flex-wrap items-center gap-1.5 min-w-0 normal-case">
            {historyLink ? (
                <Link {...historyLink} target="_blank" targetBlankIcon className="min-w-0 break-words">
                    {name}
                </Link>
            ) : (
                <span className="whitespace-normal break-words min-w-0 max-w-full">{name}</span>
            )}
            <LemonTag type="muted" size="small" className="shrink-0" weight="normal">
                {`v${scorer.version}`}
            </LemonTag>
        </div>
    )
}
