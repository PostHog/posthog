import { IconChevronRight, IconCopy } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import type { PlaygroundCitationChunk } from './playgroundCitationsLogic'

export interface PlaygroundCitationRowProps {
    chunk: PlaygroundCitationChunk
    /** Search position. Omitted for chunks read in document order. */
    rank?: number
    cited: boolean
}

export function PlaygroundCitationRow({ chunk, rank, cited }: PlaygroundCitationRowProps): JSX.Element {
    const title = chunk.document_title || chunk.source_name
    const location = [title !== chunk.source_name ? chunk.source_name : '', chunk.heading_path]
        .filter(Boolean)
        .join(' · ')

    return (
        <details className="group min-w-0">
            <summary className="flex min-w-0 cursor-pointer list-none items-center gap-1.5 py-0.5 [&::-webkit-details-marker]:hidden">
                <IconChevronRight className="shrink-0 text-secondary transition-transform group-open:rotate-90 motion-reduce:transition-none" />
                {rank !== undefined ? <span className="shrink-0 text-secondary tabular-nums">{`#${rank}`}</span> : null}
                <span className="max-w-fit min-w-0 shrink truncate font-semibold">{title}</span>
                {cited ? (
                    <LemonTag size="small" type="success" className="shrink-0">
                        Cited
                    </LemonTag>
                ) : null}
                <span className="min-w-0 flex-1 truncate text-secondary group-open:invisible">{chunk.content}</span>
            </summary>
            <div className="ml-5 flex flex-col gap-1 pb-2">
                {location ? <span className="text-xs text-secondary">{location}</span> : null}
                <div className="break-words whitespace-pre-wrap">{chunk.content}</div>
                <div className="flex flex-wrap gap-1">
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        icon={<IconCopy />}
                        onClick={() => void copyToClipboard(chunk.content, 'chunk')}
                    >
                        Copy
                    </LemonButton>
                    {chunk.url ? (
                        <LemonButton size="xsmall" type="secondary" to={chunk.url} targetBlank>
                            Open page
                        </LemonButton>
                    ) : null}
                </div>
            </div>
        </details>
    )
}
