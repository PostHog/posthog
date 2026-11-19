import { useEffect, useRef } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { DataModelingNode } from '~/types'

import { LineageSearchMode, searchResultCountLabel, searchResultWindow } from './lineageSearch'
import { NodeTypeTag } from './NodeTypeTag'

export interface LineageSearchResultsProps {
    results: DataModelingNode[]
    selectedResultId?: string
    anchorResultId?: string
    mode: LineageSearchMode
    onSelect: (nodeId: string) => void
    onPrevious: () => void
    onNext: () => void
}

export function LineageSearchResults({
    results,
    selectedResultId,
    anchorResultId,
    mode,
    onSelect,
    onPrevious,
    onNext,
}: LineageSearchResultsProps): JSX.Element {
    const selectedOptionRef = useRef<HTMLDivElement>(null)
    const { selectedPosition, renderedResults } = searchResultWindow(results, selectedResultId)
    const resultCountLabel = searchResultCountLabel(results.length, mode)

    useEffect(() => {
        selectedOptionRef.current?.scrollIntoView({ block: 'nearest' })
    }, [selectedResultId])

    return (
        <div className="absolute top-3 left-3 z-10 w-80 max-w-[calc(100%-1.5rem)] rounded border bg-bg-light shadow-lg">
            <div className="flex items-center justify-between gap-2 border-b px-2 py-1.5 text-xs text-secondary">
                <span>{resultCountLabel}</span>
                {results.length > 0 && (
                    <div className="flex items-center gap-1">
                        <span>
                            {selectedPosition} of {results.length}
                        </span>
                        <LemonButton
                            size="xsmall"
                            noPadding
                            icon={<IconChevronRight className="-rotate-90" />}
                            aria-label="Previous result"
                            tooltip="Previous result"
                            onClick={onPrevious}
                            data-attr="models-lineage-search-previous"
                        />
                        <LemonButton
                            size="xsmall"
                            noPadding
                            icon={<IconChevronRight className="rotate-90" />}
                            aria-label="Next result"
                            tooltip="Next result"
                            onClick={onNext}
                            data-attr="models-lineage-search-next"
                        />
                    </div>
                )}
            </div>
            <div className="max-h-56 overflow-y-auto p-1">
                {results.length === 0 ? (
                    <div className="px-2 py-3 text-sm text-secondary">No matching models</div>
                ) : (
                    renderedResults.map((node) => (
                        <div key={node.id} ref={node.id === selectedResultId ? selectedOptionRef : undefined}>
                            <LemonButton
                                fullWidth
                                size="small"
                                type="tertiary"
                                active={node.id === selectedResultId}
                                aria-current={node.id === selectedResultId}
                                className="justify-start"
                                onClick={() => onSelect(node.id)}
                                data-attr="models-lineage-search-result"
                            >
                                <span className="flex min-w-0 items-center gap-2">
                                    <NodeTypeTag type={node.type} />
                                    <span className="truncate">{node.name}</span>
                                    {node.id === anchorResultId && (
                                        <span className="ml-auto shrink-0 text-xs text-secondary">Anchor</span>
                                    )}
                                </span>
                            </LemonButton>
                        </div>
                    ))
                )}
            </div>
            <div className="border-t px-2 py-1.5 text-[11px] text-secondary">
                ↑↓ to select · Enter to center · Esc to clear
            </div>
        </div>
    )
}
