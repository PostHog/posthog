import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { PlayerShareRecording } from 'scenes/session-recordings/player/share/PlayerShare'
import { PlayerShareLogicProps } from 'scenes/session-recordings/player/share/playerShareLogic'

import { mswDecorator } from '~/mocks/browser'

type Story = StoryObj<typeof PlayerShareRecording>
const meta: Meta<typeof PlayerShareRecording> = {
    title: 'Replay/Sharing',
    component: PlayerShareRecording,
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/session_recordings/:recording_id/sharing': () => [
                    200,
                    {
                        created_at: '2025-01-30T19:46:47.564036Z',
                        enabled: true,
                        access_token: 'XqolMTyFCdDrwtUscDLOHSajf1oAYg',
                    },
                ],
            },
        }),
    ],
}
export default meta

export const Template: StoryFn<typeof PlayerShareRecording> = (props: PlayerShareLogicProps) => {
    return (
        <div>
            <div className="border p-4">
                <PlayerShareRecording {...props} />
            </div>
        </div>
    )
}

export const PrivateLink: Story = Template.bind({})
PrivateLink.args = {
    seconds: 720,
    id: '1',
    shareType: 'private',
}

export const PublicLink: Story = Template.bind({})
PublicLink.args = {
    seconds: 325,
    id: '1',
    shareType: 'public',
}

export const LinearLink: Story = Template.bind({})
LinearLink.args = {
    seconds: 120,
    id: '1',
    shareType: 'linear',
}
