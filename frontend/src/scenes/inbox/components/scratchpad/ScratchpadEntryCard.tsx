import { useState } from 'react'

import { IconChevronDown, IconClock } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import type { ScratchpadEntryApi } from 'products/signals/frontend/generated/api.schemas'

/**
 * One scratchpad note the scout fleet has written about this project. Shares the collapse/expand
 * grammar of the scout emission cards: a header (chevron · key · updated time) that stays visible,
 * a 2-line markdown preview when collapsed, the full body plus a written-by footer when open.
 *
 * The key is the scout-chosen semantic handle (often namespaced, e.g. `tags:errors:taxonomy`), so it
 * is rendered mono as the title — it is the most information-dense thing about the entry.
 */
export function ScratchpadEntryCard({ entry }: { entry: ScratchpadEntryApi }): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    // Lineage exists but is indirect (`created_by_run_id` → run → skill). Until the serializer
    // resolves the skill name, surface only that a scout run authored it, not which scout.
    const writtenByScout = !!entry.created_by_run_id

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
                <span className="truncate font-mono text-xs text-primary">{entry.key}</span>
                {writtenByScout && (
                    <LemonTag type="muted" size="small" className="shrink-0">
                        scout
                    </LemonTag>
                )}
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

                {expanded && (entry.created_at || writtenByScout) && (
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t pt-2 mt-2 text-xs text-tertiary">
                        {entry.created_at && <span>First noted {humanFriendlyDetailedTime(entry.created_at)}</span>}
                        {writtenByScout && (
                            <>
                                <span className="flex-1" />
                                <span className="shrink-0">Recorded by a scout run</span>
                            </>
                        )}
                    </div>
                )}
            </div>
        </div>
    )
}
