import clsx from 'clsx'
import { useActions } from 'kea'
import { useEffect, useMemo, useRef, useState } from 'react'

import { IconCollapse, IconExpand, IconNotebook } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import {
    InsightBreakdownSummary,
    PropertiesSummary,
    SeriesSummary,
} from 'lib/components/Cards/InsightCard/InsightDetails'
import { TopHeading } from 'lib/components/Cards/InsightCard/TopHeading'
import { JSONContent } from 'lib/components/RichContentEditor/types'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { NotebookNodeType, NotebookTarget } from 'scenes/notebooks/types'
import {
    SessionRecordingPlayer,
    SessionRecordingPlayerProps,
} from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { SessionRecordingPlayerMode } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { urls } from 'scenes/urls'

import { notebooksModel } from '~/models/notebooksModel'
import { Query } from '~/queries/Query/Query'
import {
    DocumentBlock,
    ErrorBlock,
    LoadingBlock,
    MarkdownBlock,
    SessionReplayBlock,
    VisualizationBlock,
} from '~/queries/schema/schema-assistant-artifacts'
import { NotebookArtifactContent } from '~/queries/schema/schema-assistant-messages'
import { DataVisualizationNode, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { isFunnelsQuery, isHogQLQuery, isInsightVizNode } from '~/queries/utils'

import { MarkdownMessage } from '../MarkdownMessage'
import { MessageStatus } from '../maxLogic'
import { castAssistantQuery, visualizationTypeToQuery } from '../utils'
import { markdownToTiptap } from '../utils/markdownToTiptap'
import { MessageTemplate } from './MessageTemplate'

interface NotebookArtifactAnswerProps {
    content: NotebookArtifactContent
    status?: MessageStatus
}

const MAX_COLLAPSED_HEIGHT_PX = 400

export function NotebookArtifactAnswer({ content, status }: NotebookArtifactAnswerProps): JSX.Element | null {
    const { createNotebook } = useActions(notebooksModel)
    const [isExpanded, setIsExpanded] = useState(false)
    const [needsExpansion, setNeedsExpansion] = useState(false)
    const contentRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        if (contentRef.current && status === 'completed') {
            setNeedsExpansion(contentRef.current.scrollHeight > MAX_COLLAPSED_HEIGHT_PX)
        }
    }, [content.blocks, status])

    if (status !== 'completed') {
        return (
            <MessageTemplate type="ai" className="w-full" wrapperClassName="w-full" boxClassName="flex flex-col w-full">
                <div className="p-2">
                    <div className="flex items-center gap-2 mb-3">
                        <IconNotebook className="size-5 text-secondary" />
                        <LemonSkeleton className="h-5 w-32" />
                    </div>
                    <LemonSkeleton className="h-20 w-full" />
                </div>
            </MessageTemplate>
        )
    }

    const handleCreateNotebook = (): void => {
        // Convert blocks to tiptap JSONContent[] format
        const tiptapContent = blocksToTiptapContent(content.blocks)

        createNotebook(NotebookTarget.Scene, content.title || 'AI Generated Notebook', tiptapContent)
    }

    const handleExpandClick = (): void => {
        if (needsExpansion && !isExpanded) {
            setIsExpanded(true)
        }
    }

    return (
        <MessageTemplate type="ai" className="w-full" wrapperClassName="w-full" boxClassName="flex flex-col w-full">
            <div className="p-2">
                <div className="flex items-center gap-2 mb-3">
                    <IconNotebook className="size-5 text-secondary" />
                    <h4 className="font-semibold m-0 text-sm">{content.title || 'Notebook'}</h4>
                </div>

                {/* Render each block as a read-only preview */}
                <div
                    ref={contentRef}
                    onClick={handleExpandClick}
                    className={clsx(
                        'space-y-3 relative',
                        needsExpansion && !isExpanded && 'cursor-pointer max-h-[400px] overflow-hidden'
                    )}
                >
                    {content.blocks.map((block, i) => (
                        <NotebookBlockPreview key={i} block={block} />
                    ))}
                    {needsExpansion && !isExpanded && (
                        <div className="absolute bottom-0 left-0 right-0 h-24 pointer-events-none bg-gradient-to-b from-transparent to-bg-light" />
                    )}
                </div>

                <div className="mt-4 flex justify-end">
                    <LemonButton onClick={handleCreateNotebook} type="primary" size="small" icon={<IconOpenInNew />}>
                        Create notebook
                    </LemonButton>
                </div>
            </div>
        </MessageTemplate>
    )
}

interface NotebookBlockPreviewProps {
    block: DocumentBlock
}

function NotebookBlockPreview({ block }: NotebookBlockPreviewProps): JSX.Element | null {
    switch (block.type) {
        case 'markdown':
            return <MarkdownBlockPreview block={block} />
        case 'visualization':
            return <VisualizationBlockPreview block={block} />
        case 'session_replay':
            return <SessionReplayBlockPreview block={block} />
        case 'loading':
            return <LoadingBlockPreview block={block} />
        case 'error':
            return <ErrorBlockPreview block={block} />
        default:
            return null
    }
}

function MarkdownBlockPreview({ block }: { block: MarkdownBlock }): JSX.Element {
    return <MarkdownMessage content={block.content} id="notebook-preview" />
}

function VisualizationBlockPreview({ block }: { block: VisualizationBlock }): JSX.Element {
    const [isSummaryShown, setIsSummaryShown] = useState(false)

    const query = useMemo(() => {
        return visualizationTypeToQuery(block)
    }, [block])

    if (!query) {
        return (
            <div className="border border-dashed rounded p-3 text-center text-muted text-sm">
                <IconNotebook className="size-4 inline-block mr-1" />
                Failed to load visualization
            </div>
        )
    }

    return (
        <div className="border rounded overflow-hidden">
            <div className={clsx('flex flex-col overflow-auto', isFunnelsQuery(block.query) ? 'h-[580px]' : 'h-96')}>
                <Query query={query} readOnly embedded />
            </div>
            <div className="flex items-center justify-between px-2 py-1 bg-surface-secondary border-t">
                <LemonButton
                    sideIcon={isSummaryShown ? <IconCollapse /> : <IconExpand />}
                    onClick={() => setIsSummaryShown(!isSummaryShown)}
                    size="xsmall"
                    className="-m-1 shrink"
                    tooltip={isSummaryShown ? 'Hide definition' : 'Show definition'}
                >
                    <span className="text-xs font-medium">
                        <TopHeading query={query} />
                    </span>
                </LemonButton>
                <LemonButton
                    to={urls.insightNew({ query: query as InsightVizNode | DataVisualizationNode })}
                    icon={<IconOpenInNew />}
                    size="xsmall"
                    tooltip="Open as new insight"
                />
            </div>
            {isInsightVizNode(query) && isSummaryShown && (
                <div className="px-2 py-1 border-t">
                    <SeriesSummary query={query.source} heading={null} />
                    {!isHogQLQuery(query.source) && (
                        <div className="flex flex-wrap gap-4 mt-1 *:grow">
                            <PropertiesSummary properties={query.source.properties} />
                            <InsightBreakdownSummary query={query.source} />
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}

function SessionReplayBlockPreview({ block }: { block: SessionReplayBlock }): JSX.Element {
    const recordingLogicProps: SessionRecordingPlayerProps = {
        sessionRecordingId: block.session_id,
        playerKey: `notebook-artifact-${block.session_id}`,
        autoPlay: false,
        mode: SessionRecordingPlayerMode.Notebook,
        noBorder: true,
        withSidebar: false,
    }

    return (
        <div className="border rounded overflow-hidden">
            <div className="h-[400px]">
                <SessionRecordingPlayer {...recordingLogicProps} />
            </div>
            <div className="flex items-center justify-between px-2 py-1 bg-surface-secondary border-t">
                <span className="text-xs font-medium">{block.title || 'Session Replay'}</span>
                <LemonButton
                    to={urls.replaySingle(block.session_id)}
                    icon={<IconOpenInNew />}
                    size="xsmall"
                    tooltip="Open session replay"
                />
            </div>
        </div>
    )
}

function LoadingBlockPreview({ block }: { block: LoadingBlock }): JSX.Element {
    void block // Block contains artifact_id for future use
    return (
        <div className="border border-dashed rounded p-4 flex items-center gap-3">
            <LemonSkeleton className="size-8 rounded" />
            <div className="flex-1">
                <LemonSkeleton className="h-4 w-32 mb-2" />
                <LemonSkeleton className="h-3 w-48" />
            </div>
        </div>
    )
}

function ErrorBlockPreview({ block }: { block: ErrorBlock }): JSX.Element {
    return (
        <div className="border border-danger-dark rounded p-3 bg-danger-highlight text-danger text-sm">
            <span className="font-medium">Error:</span> {block.message}
        </div>
    )
}

/**
 * Convert DocumentBlock[] to tiptap JSONContent[] for notebook creation.
 */
function blocksToTiptapContent(blocks: DocumentBlock[]): JSONContent[] {
    const result: JSONContent[] = []

    for (const block of blocks) {
        switch (block.type) {
            case 'markdown':
                // Convert markdown to proper tiptap JSON structure
                result.push(...markdownToTiptap(block.content))
                break
            case 'visualization': {
                // Create a ph-query node that the notebook can render
                const source = castAssistantQuery(block.query)
                const query = isHogQLQuery(source)
                    ? { kind: NodeKind.DataVisualizationNode, source }
                    : { kind: NodeKind.InsightVizNode, source }

                result.push({
                    type: NotebookNodeType.Query,
                    attrs: {
                        query,
                        title: block.title,
                    },
                })
                break
            }
            case 'session_replay':
                result.push({
                    type: NotebookNodeType.Recording,
                    attrs: {
                        id: block.session_id,
                        __init: {
                            expanded: true,
                        },
                    },
                })
                break
        }
    }

    return result
}
