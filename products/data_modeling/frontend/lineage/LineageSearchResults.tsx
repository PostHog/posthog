import { useEffect, useRef } from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { DataModelingNode } from '~/types'

import { NodeTypeTag } from './NodeTypeTag'

export interface LineageSearchResultsProps {
    results: DataModelingNode[]
    selectedResultId?: string
    onSelect: (nodeId: string) => void
    onPrevious: () => void
    onNext: () => void
}

export function LineageSearchResults({
    results,
    selectedResultId,
    onSelect,
    onPrevious,
    onNext,
}: LineageSearchResultsProps): JSX.Element {
    const selectedOptionRef = useRef<HTMLDivElement>(null)
    const selectedPosition = results.findIndex((node) => node.id === selectedResultId) + 1
    const selectedResult = results[selectedPosition - 1]

    useEffect(() => {
        selectedOptionRef.current?.scrollIntoView({ block: 'nearest' })
    }, [selectedResultId])

    return (
        <div className="absolute top-3 left-3 z-10 w-80 max-w-[calc(100%-1.5rem)] rounded border bg-bg-light shadow-lg">
            <span className="sr-only" aria-live="polite">
                {selectedResult
                    ? `${selectedResult.name}, result ${selectedPosition} of ${results.length}`
                    : 'No matching models'}
            </span>
            <div className="flex items-center justify-between gap-2 border-b px-2 py-1.5 text-xs text-secondary">
                <span aria-live="polite">
                    {results.length} {results.length === 1 ? 'result' : 'results'}
                </span>
                {results.length > 0 && (
                    <div className="flex items-center gap-1">
                        <span>
                            {selectedPosition} of {results.length}
                        </span>
                        <LemonButton
                            size="xsmall"
                            noPadding
                            icon={<IconChevronLeft />}
                            aria-label="Previous result"
                            tooltip="Previous result"
                            onClick={onPrevious}
                            data-attr="models-lineage-search-previous"
                        />
                        <LemonButton
                            size="xsmall"
                            noPadding
                            icon={<IconChevronRight />}
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
                    results.map((node) => (
                        <div key={node.id} ref={node.id === selectedResultId ? selectedOptionRef : undefined}>
                            <LemonButton
                                fullWidth
                                size="small"
                                type="tertiary"
                                active={node.id === selectedResultId}
                                aria-pressed={node.id === selectedResultId}
                                className="justify-start"
                                onClick={() => onSelect(node.id)}
                                data-attr="models-lineage-search-result"
                            >
                                <span className="flex min-w-0 items-center gap-2">
                                    <NodeTypeTag type={node.type} />
                                    <span className="truncate">{node.name}</span>
                                </span>
                            </LemonButton>
                        </div>
                    ))
                )}
            </div>
        </div>
    )
}
