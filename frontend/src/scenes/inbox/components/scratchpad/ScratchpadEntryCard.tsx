import { type ComponentProps, useState } from 'react'

import { IconChevronDown, IconClock } from '@posthog/icons'
import { LemonTag, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import type { ScratchpadEntryApi } from 'products/signals/frontend/generated/api.schemas'

import { stripScoutPrefix } from '../../utils/scoutRunsWindow'

type LemonTagType = ComponentProps<typeof LemonTag>['type']

// The key prefix (everything before the first colon) encodes the note's *kind* — what the scout
// was doing when it wrote it. Surface it as a colored tag so the list scans at a glance.
const KIND_TAG_TYPE: Record<string, LemonTagType> = {
    pattern: 'highlight',
    dedupe: 'muted',
    noise: 'muted',
    baseline: 'success',
    watch: 'warning',
    watchlist: 'warning',
    coverage: 'completion',
    emerging: 'primary',
    explore: 'option',
    tags: 'option',
    recheck: 'caution',
}

function splitKey(key: string): { kind: string | null; body: string } {
    const idx = key.indexOf(':')
    return idx > 0 ? { kind: key.slice(0, idx), body: key.slice(idx + 1) } : { kind: null, body: key }
}

/**
 * One scratchpad note the scout fleet has written about this project. Shares the collapse/expand
 * grammar of the scout emission cards: a header (chevron · kind · key · updated time) that stays
 * visible, a 2-line markdown preview when collapsed, the full body plus an attribution footer
 * (which scout created it, when, and how long it's been carried forward) when open.
 */
export function ScratchpadEntryCard({ entry }: { entry: ScratchpadEntryApi }): JSX.Element {
    const [expanded, setExpanded] = useState(false)

    const { kind, body } = splitKey(entry.key)
    const scoutName = entry.created_by_skill ? stripScoutPrefix(entry.created_by_skill) : null

    // How long the note has been carried forward: a fresh creation reads ~0 days; a large gap
    // means the fleet has re-touched this learning across many runs — the "gets sharper" signal.
    const maintainedDays =
        entry.created_at && entry.updated_at ? dayjs(entry.updated_at).diff(dayjs(entry.created_at), 'day') : 0

    return (
        <div className="flex flex-col rounded border border-primary bg-bg-light">
            <button
                type="button"
                onClick={() => setExpanded((value) => !value)}
                className="flex items-center gap-2 px-3 py-2 text-left"
                aria-expanded={expanded}
            >
                <IconChevronDown
                    className={`size-4 shrink-0 text-muted transition-transform ${expanded ? '' : '-rotate-90'}`}
                />
                {kind && (
                    <LemonTag type={KIND_TAG_TYPE[kind] ?? 'muted'} size="small" className="shrink-0">
                        {kind}
                    </LemonTag>
                )}
                <span className="truncate font-mono text-xs text-primary">{body}</span>
                <span className="flex-1" />
                {entry.updated_at && (
                    <span className="flex items-center gap-1 whitespace-nowrap text-[11px] text-muted">
                        <IconClock className="size-3" />
                        {humanFriendlyDetailedTime(entry.updated_at)}
                    </span>
                )}
            </button>

            <div className="px-3 pb-2 pl-9">
                <LemonMarkdown
                    disableImages
                    className={expanded ? 'text-sm text-primary' : 'text-sm text-primary line-clamp-2'}
                >
                    {entry.content || '_No content._'}
                </LemonMarkdown>

                {expanded && (entry.created_at || scoutName || entry.created_by_run_id) && (
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t pt-2 mt-2 text-xs text-tertiary">
                        {entry.created_at && <span>Created {humanFriendlyDetailedTime(entry.created_at)}</span>}
                        {maintainedDays >= 1 && (
                            <span>· carried forward {maintainedDays === 1 ? '1 day' : `${maintainedDays} days`}</span>
                        )}
                        <span className="flex-1" />
                        {(scoutName || entry.created_by_run_id) && (
                            <span className="shrink-0">
                                by{' '}
                                {entry.created_by_run_url ? (
                                    <Link to={entry.created_by_run_url}>
                                        {scoutName ? `${scoutName} scout` : 'a scout'}
                                    </Link>
                                ) : scoutName ? (
                                    `${scoutName} scout`
                                ) : (
                                    'a scout'
                                )}
                            </span>
                        )}
                    </div>
                )}
            </div>
        </div>
    )
}
