import type { Meta, StoryObj } from '@storybook/react'

import { LifecycleStrip } from './LifecycleStrip'

const meta: Meta<typeof LifecycleStrip> = {
    title: 'Data catalog/Lifecycle strip',
    component: LifecycleStrip,
    parameters: { viewMode: 'story' },
    render: (props) => (
        // A fixed width keeps the wrap point, and so the baseline, the same on every run.
        <div className="@container w-240 p-4">
            <LifecycleStrip {...props} />
        </div>
    ),
}
export default meta

export const DriftedSelected: StoryObj<typeof LifecycleStrip> = {
    args: { counts: { proposed: 7, approved: 42, drifted: 2 }, status: 'drifted', onToggle: () => {} },
}
