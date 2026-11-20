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
        <div className="flex flex-col gap-6">
            {visibleBlocks.map((key) => (
                <div
                    key={key}
                    ref={key === highlightedBlock ? highlightRef : undefined}
                    className={
                        key === highlightedBlock ? 'rounded-sm outline-2 outline-offset-4 outline-primary' : undefined
                    }
                >
                    {blocks[key]}
                </div>
            ))}
        </div>
    )
}
