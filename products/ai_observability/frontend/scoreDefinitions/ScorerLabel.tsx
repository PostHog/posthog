import { IconExternal } from '@posthog/icons'
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
    const version = (
        <LemonTag type="muted" size="small" className="shrink-0" weight="normal">
            {`v${scorer.version}`}
        </LemonTag>
    )
    return historyLink ? (
        <Link
            {...historyLink}
            target="_blank"
            className="group/scorer inline-flex max-w-full flex-wrap items-center gap-1 normal-case hover:no-underline"
        >
            <span className="min-w-0 max-w-full whitespace-normal break-words group-hover/scorer:underline">
                {name}
            </span>
            <div className="inline-flex items-center gap-1">
                <IconExternal className="size-2.5" aria-hidden="true" />
                {version}
            </div>
        </Link>
    ) : (
        <div className="flex flex-wrap items-center gap-1.5 min-w-0 normal-case">
            <span className="min-w-0 max-w-full whitespace-normal break-words">{name}</span>
            {version}
        </div>
    )
}
