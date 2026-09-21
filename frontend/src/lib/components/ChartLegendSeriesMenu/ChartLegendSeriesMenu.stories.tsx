import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { ChartLegendSeriesMenu } from './ChartLegendSeriesMenu'

const SERIES = [
    { key: 'pageviews', label: 'Pageviews', color: 'var(--data-color-1)' },
    { key: 'signups', label: 'Signups', color: 'var(--data-color-2)' },
    { key: 'purchases', label: 'Purchases', color: 'var(--data-color-3)' },
]

type Story = StoryObj<typeof ChartLegendSeriesMenu>
const meta: Meta<typeof ChartLegendSeriesMenu> = {
    title: 'Components/Chart legend series menu',
    component: ChartLegendSeriesMenu,
    tags: ['autodocs'],
}
export default meta

/** A stand-in for the real quill chart legend: same click model (plain click isolates, ⌘/Ctrl-click
 *  adds), so the menu's labels can be exercised without mounting a chart. */
function LegendHarness({ items }: { items: typeof SERIES }): JSX.Element {
    const [hidden, setHidden] = useState<string[]>([])
    const rowKeys = items.map((item) => item.key)
    const visibleCount = rowKeys.filter((key) => !hidden.includes(key)).length

    const toggle = (key: string): void =>
        setHidden((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]))

    const isolate = (key: string): void => {
        const others = rowKeys.filter((k) => k !== key)
        const isolated = !hidden.includes(key) && others.every((k) => hidden.includes(k))
        setHidden(isolated ? [] : others)
    }

    return (
        <div className="flex w-[420px] flex-row gap-3 rounded border border-primary bg-surface-primary p-3">
            {items.map((item) => {
                const isHidden = hidden.includes(item.key)
                return (
                    <ChartLegendSeriesMenu
                        key={item.key}
                        seriesLabel={item.label}
                        seriesColor={item.color}
                        isHidden={isHidden}
                        isOnlyVisible={rowKeys.length > 1 && visibleCount === 1 && !isHidden}
                        areAllVisible={hidden.length === 0}
                        canIsolate={rowKeys.length > 1}
                        onToggle={() => toggle(item.key)}
                        onIsolate={() => isolate(item.key)}
                        onToggleAll={() => setHidden(hidden.length === 0 ? rowKeys : [])}
                    >
                        <button
                            type="button"
                            className={`inline-flex select-none items-center gap-1.5 border-0 bg-transparent p-0 text-xs ${
                                isHidden ? 'opacity-40' : ''
                            }`}
                            onClick={(event) =>
                                event.metaKey || event.ctrlKey || rowKeys.length === 1
                                    ? toggle(item.key)
                                    : isolate(item.key)
                            }
                        >
                            <span
                                aria-hidden="true"
                                // eslint-disable-next-line react/forbid-dom-props -- swatch takes the series color
                                style={{ backgroundColor: item.color }}
                                className="size-2.5 rounded-sm"
                            />
                            {item.label}
                        </button>
                    </ChartLegendSeriesMenu>
                )
            })}
        </div>
    )
}

export const Default: Story = {
    render: () => <LegendHarness items={SERIES} />,
}

/** A single-series legend drops the isolate and hide-all rows — there is nothing to isolate from. */
export const SingleSeries: Story = {
    render: () => <LegendHarness items={SERIES.slice(0, 1)} />,
}
