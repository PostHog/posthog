import { useState } from 'react'

import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'

import type { KnowledgeSearchResultApi } from '../../generated/api.schemas'

// About four lines at this width. Counting avoids measuring the rendered text.
const COLLAPSE_AFTER_CHARS = 400
const COLLAPSE_AFTER_LINES = 4

export interface PlaygroundChunkProps {
    chunk: KnowledgeSearchResultApi
    rank: number
}

export function PlaygroundChunk({ chunk, rank }: PlaygroundChunkProps): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const collapsible =
        chunk.content.length > COLLAPSE_AFTER_CHARS || chunk.content.split('\n').length > COLLAPSE_AFTER_LINES
    const title = chunk.document_title || chunk.source_name

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-2 p-3">
            <div className="flex items-start gap-2">
                <span className="font-semibold text-secondary">{`#${rank}`}</span>
                <div className="flex min-w-0 flex-1 flex-col">
                    {chunk.url ? (
                        <Link to={chunk.url} target="_blank" className="truncate font-semibold">
                            {title}
                        </Link>
                    ) : (
                        <span className="truncate font-semibold">{title}</span>
                    )}
                    {title !== chunk.source_name ? (
                        <span className="truncate text-xs text-secondary">{chunk.source_name}</span>
                    ) : null}
                    {chunk.heading_path ? (
                        <span className="text-xs break-words text-secondary">{chunk.heading_path}</span>
                    ) : null}
                </div>
                <LemonButton
                    size="xsmall"
                    icon={<IconCopy />}
                    tooltip="Copy chunk"
                    onClick={() => void copyToClipboard(chunk.content, 'chunk')}
                />
            </div>
            <div
                className={cn('text-sm break-words', collapsible && !expanded ? 'line-clamp-4' : 'whitespace-pre-wrap')}
            >
                {chunk.content}
            </div>
            {collapsible ? (
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    className="self-start"
                    onClick={() => setExpanded(!expanded)}
                >
                    {expanded ? 'Show less' : 'Show full chunk'}
                </LemonButton>
            ) : null}
        </LemonCard>
    )
}
