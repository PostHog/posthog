import type { Meta, StoryObj } from '@storybook/react'

import { DotGlyph } from './DotGlyph'
import { DotMatrix } from './DotMatrix'
import { DotMatrixDemo } from './DotMatrixDemo'
import { DOT_MATRIX_MOCK_GROUPS, getDotMatrixMockDataset } from './mocks'

const meta: Meta<typeof DotMatrixDemo> = {
    title: 'Components/Dot matrix',
    component: DotMatrixDemo,
    parameters: { layout: 'padded', mockDate: '2026-11-03', testOptions: { waitForSelector: '.DotMatrix' } },
    args: { instanceId: 'dot-matrix-story' },
}
export default meta

type Story = StoryObj<typeof DotMatrixDemo>

export const Products: Story = {}
export const PerProduct: Story = { args: { initialColorMode: 'product' } }
export const Count: Story = { args: { initialMode: 'count' } }
export const SelectedProduct: Story = { args: { initialMode: 'count', initialSelection: ['replay'] } }
export const SelectedUnion: Story = { args: { initialMode: 'count', initialSelection: ['logs', 'tracing'] } }
export const Users: Story = { args: { initialMode: 'users' } }
export const Account: Story = { args: { initialMode: 'account' } }
export const People: Story = { args: { initialDataset: 'people' } }
export const CI: Story = { args: { initialDataset: 'ci' } }
export const Narrow: Story = { args: { width: 'narrow' } }
export const Wide: Story = { args: { width: 'wide' } }
export const Empty: Story = { args: { empty: true } }
export const Loading: Story = { args: { loading: true, empty: true } }
export const Thresholds: Story = {
    render: () => (
        <div className="flex flex-col gap-4">
            <div className="flex gap-4">
                {[0, 1, 5, 10].map((value) => (
                    <div key={value} className="flex flex-col gap-2">
                        <span>{value}</span>
                        <DotGlyph
                            series={Array.from({ length: 18 }, (_, index) => ({
                                key: String(index),
                                group: DOT_MATRIX_MOCK_GROUPS[Math.floor(index / 6)].key,
                            }))}
                            groups={DOT_MATRIX_MOCK_GROUPS}
                            values={Object.fromEntries(
                                Array.from({ length: 18 }, (_, index) => [String(index), value])
                            )}
                            label={`${value} users in every series`}
                        />
                    </div>
                ))}
            </div>
            <DotMatrix {...getDotMatrixMockDataset('ci')} data={getDotMatrixMockDataset('ci').data.slice(0, 12)} />
        </div>
    ),
}
