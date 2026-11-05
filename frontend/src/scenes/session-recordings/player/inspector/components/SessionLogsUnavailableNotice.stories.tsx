import type { Meta, StoryObj } from '@storybook/react'

import { SessionLogsUnavailableNotice } from 'scenes/session-recordings/player/inspector/components/SessionLogsUnavailableNotice'

type Story = StoryObj<typeof SessionLogsUnavailableNotice>
const meta: Meta<typeof SessionLogsUnavailableNotice> = {
    title: 'Components/PlayerInspector/SessionLogsUnavailableNotice',
    component: SessionLogsUnavailableNotice,
    render: (props) => (
        <div className="w-100 border rounded bg-surface-primary">
            <SessionLogsUnavailableNotice {...props} />
        </div>
    ),
}
export default meta

export const Default: Story = {
    args: { sessionId: '01900000-0000-0000-0000-000000000001' },
}
