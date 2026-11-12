import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { CountCell } from './CountCell'
import { DotGlyph } from './DotGlyph'
import { DotMatrix } from './DotMatrix'
import { DOT_MATRIX_SIZE_THRESHOLDS } from './dotMatrixPresentation'
import type { DotMatrixProps } from './types'

type Datum = { account: string; week: string; product: string; users: number }

const fixture: DotMatrixProps<Datum> = {
    fields: { row: 'account', column: 'week', series: 'product', value: 'users' },
    rows: [{ key: 'North' }, { key: 'South' }, { key: 'West' }],
    columns: [{ key: 'Week 1' }, { key: 'Week 2' }, { key: 'Week 3', partial: true }],
    series: [
        { key: 'analytics', label: 'Analytics', group: 'understand' },
        { key: 'replay', label: 'Session replay', group: 'understand' },
        { key: 'flags', label: 'Feature flags', group: 'ship' },
        { key: 'experiments', label: 'Experiments', group: 'ship' },
    ],
    groups: [
        { key: 'understand', label: 'Understand', color: 'var(--data-color-1)' },
        { key: 'ship', label: 'Ship', color: 'var(--data-color-2)' },
    ],
    data: ['North', 'South', 'West'].flatMap((account, row) =>
        ['Week 1', 'Week 2', 'Week 3'].flatMap((week, column) =>
            ['analytics', 'replay', 'flags', 'experiments'].map((product, series) => ({
                account,
                week,
                product,
                users: [0, 1, 5, 10][(row + column + series) % 4],
            }))
        )
    ),
    rowHeader: { title: 'Account' },
    aggregateSelection: (cell, selected) => selected.filter((key) => cell.values[key] > 0).length,
    legend: { itemLabel: 'products', valueLabel: 'Users', hint: 'Click a product to filter. Shift-click to add more.' },
}

const meta: Meta<DotMatrixProps<Datum>> = {
    title: 'Components/Dot matrix',
    component: DotMatrix,
    parameters: { layout: 'padded', testOptions: { waitForSelector: '.DotMatrix' } },
    args: fixture,
    render: function Render(args) {
        const [selectedSeries, setSelectedSeries] = useState(args.selectedSeries)
        return (
            <div className="w-[1100px] max-w-full">
                <DotMatrix {...args} selectedSeries={selectedSeries} onSelectedSeriesChange={setSelectedSeries} />
            </div>
        )
    },
}
export default meta

type Story = StoryObj<DotMatrixProps<Datum>>

export const Products: Story = {}
export const PerProduct: Story = { args: { groups: [] } }
export const Count: Story = { args: { mode: 'count' } }
export const SelectedProduct: Story = { args: { mode: 'count', selectedSeries: ['replay'] } }
export const SelectedUnion: Story = { args: { mode: 'count', selectedSeries: ['analytics', 'replay'] } }
export const FirstUse: Story = {
    args: { firstUseSeries: (cell) => (cell.columnKey === 'Week 1' ? ['replay'] : []) },
}
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-128">
                <Story />
            </div>
        ),
    ],
}
export const Empty: Story = { args: { data: [], rows: [] } }
export const Loading: Story = {
    args: { loading: true, data: [], rows: [] },
    parameters: {
        testOptions: { waitForLoadersToDisappear: false, waitForSelector: '.DotMatrix .LemonSkeleton' },
    },
}
export const CustomFields: Story = {
    render: () => (
        <div className="w-[1100px] max-w-full">
            <DotMatrix
                data={[
                    { station: 'North station', inspection: 'Morning', faults: 2 },
                    { station: 'North station', inspection: 'Evening', faults: 0 },
                    { station: 'South station', inspection: 'Morning', faults: 4 },
                    { station: 'South station', inspection: 'Evening', faults: 1 },
                ]}
                fields={{ row: 'station', column: 'inspection', value: 'faults' }}
                rowHeader={{ title: 'Station' }}
            />
        </div>
    ),
}
export const Thresholds: Story = {
    parameters: { testOptions: { waitForSelector: '.DotGlyph' } },
    render: () => (
        <div className="flex gap-4">
            {[0, ...DOT_MATRIX_SIZE_THRESHOLDS].map((value) => (
                <div key={value} className="flex flex-col gap-2">
                    <span>{value}</span>
                    <DotGlyph
                        series={fixture.series!}
                        groups={fixture.groups}
                        values={Object.fromEntries(fixture.series!.map(({ key }) => [key, value]))}
                        label={`${value} users in every series`}
                    />
                </div>
            ))}
        </div>
    ),
}

export const LargeCounts: Story = {
    parameters: { testOptions: { waitForSelector: '.CountCell' } },
    render: () => (
        <div className="flex flex-col gap-2">
            {(['xsmall', 'small', 'medium'] as const).map((size) => (
                <div key={size} className="flex items-center gap-4">
                    <span className="w-16">{size}</span>
                    {[100_000, 1_000_000, 1_234_567].map((value) => (
                        <CountCell key={value} value={value} size={size} />
                    ))}
                </div>
            ))}
        </div>
    ),
}
