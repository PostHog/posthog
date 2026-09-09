import type { Meta, StoryObj } from '@storybook/react'

import { IncludesTestUsersNotice } from './IncludesTestUsersNotice'

const meta: Meta<typeof IncludesTestUsersNotice> = {
    title: 'Components/Cards/Includes Test Users Notice',
    component: IncludesTestUsersNotice,
    tags: ['autodocs'],
}
export default meta

type Story = StoryObj<typeof IncludesTestUsersNotice>

export const FromInsight: Story = { args: { source: 'insight' } }
export const FromDashboard: Story = { args: { source: 'dashboard' } }
export const FromTile: Story = { args: { source: 'tile' } }
