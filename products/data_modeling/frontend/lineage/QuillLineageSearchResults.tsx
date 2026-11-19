import { useEffect, useRef } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { Button, Card, Text, cn } from '@posthog/quill'

import { searchResultCountLabel, searchResultWindow } from './lineageSearch'
import { LineageSearchResultsProps } from './LineageSearchResults'
import { QuillNodeTypeTag } from './QuillNodeTypeTag'

export function QuillLineageSearchResults({
    results,
    selectedResultId,
    anchorResultId,
    mode,
    onSelect,
    onPrevious,
    onNext,
}: LineageSearchResultsProps): JSX.Element {
    const selectedOptionRef = useRef<HTMLButtonElement>(null)
    const { selectedPosition, renderedResults } = searchResultWindow(results, selectedResultId)

    useEffect(() => {
        selectedOptionRef.current?.scrollIntoView({ block: 'nearest' })
    }, [selectedResultId])

    return (
        <Card
            size="sm"
            className="absolute top-3 left-3 z-10 w-80 max-w-[calc(100%-1.5rem)] gap-0 py-0 shadow-lg"
            data-attr="models-lineage-search-results"
        >
            <div className="flex items-center justify-between gap-2 border-b border-border px-2 py-1">
                <Text size="xs" variant="muted">
                    {searchResultCountLabel(results.length, mode)}
                </Text>
                {results.length > 0 && (
                    <div className="flex items-center gap-1">
                        <Text size="xs" variant="muted" className="tabular-nums">
                            {selectedPosition} of {results.length}
                        </Text>
                        <Button
                            size="icon-xs"
                            aria-label="Previous result"
                            tooltip="Previous result"
                            onClick={onPrevious}
                            data-attr="models-lineage-search-previous"
                        >
                            <IconChevronDown className="rotate-180" />
                        </Button>
                        <Button
                            size="icon-xs"
                            aria-label="Next result"
                            tooltip="Next result"
                            onClick={onNext}
                            data-attr="models-lineage-search-next"
                        >
                            <IconChevronDown />
                        </Button>
                    </div>
                )}
            </div>
            <div className="max-h-56 scroll-py-4 overflow-y-auto p-1 scroll-mask-y-4">
                {results.length === 0 ? (
                    <Text size="xs" variant="muted" className="px-2 py-3">
                        No matching models
                    </Text>
                ) : (
                    renderedResults.map((node) => {
                        const selected = node.id === selectedResultId
                        return (
                            <Button
                                key={node.id}
                                ref={selected ? selectedOptionRef : undefined}
                                size="row"
                                left
                                aria-current={selected}
                                className={cn(selected && 'bg-fill-selected')}
                                onClick={() => onSelect(node.id)}
                                data-attr="models-lineage-search-result"
                            >
                                <QuillNodeTypeTag type={node.type} />
                                <span className="min-w-0 truncate">{node.name}</span>
                                {node.id === anchorResultId && (
                                    <Text size="xs" variant="muted" render={<span />} className="ml-auto shrink-0">
                                        Anchor
                                    </Text>
                                )}
                            </Button>
                        )
                    })
                )}
            </div>
            <Text size="xxs" variant="muted" className="border-t border-border px-2 py-1">
                ↑↓ to select · Enter to center · Esc to clear
            </Text>
        </Card>
    )
}
