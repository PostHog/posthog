import '../Bets.scss'

import type { Meta, StoryObj } from '@storybook/react'

import 'scenes/project-homepage/today/Today.scss'

import { BetConfiguration } from './BetConfiguration'

const meta: Meta<typeof BetConfiguration> = {
    title: 'Products/Bets/Details',
    component: BetConfiguration,
    decorators: [
        (Story) => (
            <div className="Today Bets Today__page p-6" data-quill>
                <Story />
            </div>
        ),
    ],
    args: {
        bet: {
            repository: 'example/editor',
            status: 'running',
            goal_version: 1,
            work: [],
            scout: {
                config_id: '00000000-0000-4000-8000-000000000003',
                name: 'bet-1001-v1',
                enabled: true,
                running: true,
            },
        },
    },
}
export default meta
type Story = StoryObj<typeof meta>
export const Connected: Story = {}
export const NoRepository: Story = { args: { bet: { ...meta.args!.bet!, repository: '' } } }
