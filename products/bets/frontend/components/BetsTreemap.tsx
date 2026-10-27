import { Button } from '@posthog/quill'

import { layoutTreemap } from './treemapLayout'

export interface BetsTreemapItem {
    id: string
    label: string
    value: number
    detail: string
}

export function BetsTreemap({
    items,
    selected,
    onSelect,
    label,
}: {
    items: BetsTreemapItem[]
    selected?: string | null
    onSelect: (id: string) => void
    label: string
}): JSX.Element {
    const rectangles = layoutTreemap(items)
    return (
        <div className="BetsTreemap relative w-full shrink-0" role="group" aria-label={label}>
            {rectangles.map((rect, index) => {
                const item = items.find((entry) => entry.id === rect.id)!
                return (
                    <Button
                        key={rect.id}
                        variant="outline"
                        className="BetsTreemap__tile items-start"
                        left
                        data-tone={index % 4}
                        data-selected={selected === rect.id || undefined}
                        data-small={rect.width < 20 || rect.height < 20 || undefined}
                        aria-pressed={selected === rect.id}
                        aria-label={`${item.label}, ${item.detail}`}
                        title={`${item.label} · ${item.detail}`}
                        onClick={() => onSelect(rect.id)}
                        data-attr="bets-allocation-tile"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            left: `${rect.x}%`,
                            top: `${rect.y}%`,
                            width: `${rect.width}%`,
                            height: `${rect.height}%`,
                        }}
                    >
                        <span className="BetsTreemap__text flex-col gap-1 overflow-hidden text-left">
                            <span className="BetsTreemap__name whitespace-normal">{item.label}</span>
                            <span className="BetsTreemap__value opacity-70">{item.detail}</span>
                        </span>
                    </Button>
                )
            })}
        </div>
    )
}
