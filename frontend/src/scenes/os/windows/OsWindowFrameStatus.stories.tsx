import type { Meta, StoryObj } from '@storybook/react'

import { OsFrameStatus } from './osWindowFramesLogic'
import { OsWindowFrameStatus } from './OsWindowFrameStatus'

const meta: Meta = {
    title: 'Scenes-App/OS/Window frame status',
    parameters: {
        layout: 'padded',
        viewMode: 'story',
    },
}
export default meta

type Story = StoryObj<Record<string, never>>

function WindowBody({ status }: { status: OsFrameStatus }): JSX.Element {
    return (
        <div className="relative flex h-60 w-120 rounded-md border border-primary bg-surface-primary">
            <OsWindowFrameStatus status={status} title="Workflows" onReload={() => {}} />
        </div>
    )
}

export const Loading: Story = {
    render: () => <WindowBody status="loading" />,
}

export const Slow: Story = {
    render: () => <WindowBody status="slow" />,
}
