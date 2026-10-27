import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { layoutTreemap, type TreemapRectangle } from './treemapLayout'

export interface BetsTreemapItem {
    id: string
    label: string
    value: number
    amount: string
    to?: string
    available?: boolean
}

function share(value: number, total: number): string {
    const percent = (value / total) * 100
    return percent > 0 && percent < 1 ? 'Under 1%' : `${Math.round(percent)}%`
}

function placement(rect: TreemapRectangle): { vertical: string; horizontal: string } {
    const vertical = rect.y >= 20 ? 'above' : rect.y + rect.height <= 80 ? 'below' : 'inside'
    const horizontal = rect.x < 15 ? 'start' : rect.x + rect.width > 85 ? 'end' : 'center'
    return { vertical, horizontal }
}

export function BetsTreemap({ items, label }: { items: BetsTreemapItem[]; label: string }): JSX.Element {
    const rectangles = layoutTreemap(items)
    const total = items.reduce((sum, item) => sum + Math.max(item.value, 0), 0)
    return (
        <span className="BetsTreemap" role="group" aria-label={label}>
            {rectangles.map((rect, index) => {
                const item = items.find((entry) => entry.id === rect.id)!
                const percent = share(item.value, total)
                const description = `${item.label}, ${item.amount}, ${percent} of budget`
                const { vertical, horizontal } = placement(rect)
                const text = (
                    <span className="BetsTreemap__text">
                        <span className="BetsTreemap__name">{item.label}</span>
                        <span className="BetsTreemap__value">
                            {item.amount}
                            <span className="BetsTreemap__share"> · {percent}</span>
                        </span>
                    </span>
                )
                return (
                    <span
                        key={rect.id}
                        className="BetsTreemap__cell"
                        data-vertical={vertical}
                        data-horizontal={horizontal}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            left: `${rect.x}%`,
                            top: `${rect.y}%`,
                            width: `${rect.width}%`,
                            height: `${rect.height}%`,
                        }}
                    >
                        {item.to ? (
                            <LinkPrimitive
                                to={item.to}
                                className="BetsTreemap__tile"
                                data-tone={index % 4}
                                data-available={item.available || undefined}
                                aria-label={description}
                                data-attr="bets-allocation-tile"
                            >
                                {text}
                            </LinkPrimitive>
                        ) : (
                            <span
                                className="BetsTreemap__tile"
                                data-tone={index % 4}
                                data-available={item.available || undefined}
                            >
                                {text}
                            </span>
                        )}
                        <span className="BetsTreemap__label" aria-hidden="true">
                            <span className="BetsTreemap__name">{item.label}</span>
                            <span className="BetsTreemap__value">
                                {item.amount} · {percent} of budget
                            </span>
                        </span>
                    </span>
                )
            })}
        </span>
    )
}
