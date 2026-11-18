import { RefObject } from 'react'

export function QuillUpdateEmailPreferences({
    blocks,
    visibleBlocks,
    highlightedBlock,
    highlightRef,
}: {
    blocks: Record<string, JSX.Element>
    visibleBlocks: string[]
    highlightedBlock: string | null
    highlightRef: RefObject<HTMLDivElement>
}): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            {visibleBlocks.map((key) => (
                <div
                    key={key}
                    ref={key === highlightedBlock ? highlightRef : undefined}
                    className={key === highlightedBlock ? 'ring-2 ring-primary rounded-lg' : undefined}
                >
                    {blocks[key]}
                </div>
            ))}
        </div>
    )
}
