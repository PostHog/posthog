import type { Meta, StoryObj } from '@storybook/react'

import { TraceCellValue } from './TraceCellValue'

const meta: Meta<typeof TraceCellValue> = {
    title: 'Scenes-App/AI observability/Traces/Trace cell value',
    component: TraceCellValue,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { status: 'ready', skeletonWidth: 'w-24', children: <span>2.31s</span> },
}
export default meta

type Story = StoryObj<typeof TraceCellValue>

export const Value: Story = {}

export const NoValue: Story = { args: { children: null } }

export const Loading: Story = { args: { status: 'loading' } }

export const Failed: Story = { args: { status: 'error' } }

export const NarrowContainer: Story = {
    args: { status: 'loading' },
    decorators: [
        (StoryComponent) => (
            <div className="w-12">
                <StoryComponent />
            </div>
        ),
    ],
}
