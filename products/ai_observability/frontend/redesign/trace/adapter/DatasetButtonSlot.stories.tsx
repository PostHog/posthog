import type { Meta, StoryObj } from '@storybook/react'

import { DatasetButtonSlot } from './DatasetButtonSlot'

const meta: Meta<typeof DatasetButtonSlot> = {
    title: 'Scenes-App/AI observability/Trace view/Dataset button slot',
    component: DatasetButtonSlot,
    args: { source: null, onLoad: () => {} },
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export default meta

type Story = StoryObj<typeof DatasetButtonSlot>

export const Placeholder: Story = { args: { raw: undefined } }

export const Loading: Story = {
    args: { raw: { status: 'loading' } },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}

export const LoadFailed: Story = { args: { raw: { status: 'error', failure: 'failed' } } }
