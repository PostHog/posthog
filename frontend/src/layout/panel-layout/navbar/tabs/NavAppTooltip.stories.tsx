import type { Meta, StoryObj } from '@storybook/react'

import { NavAppTooltip } from './NavAppTooltip'

const meta: Meta<typeof NavAppTooltip> = {
    title: 'Layout/Apps/App tooltip',
    component: NavAppTooltip,
    decorators: [
        (Story) => (
            <div className="Tooltip bg-[var(--color-bg-surface-tooltip)] rounded p-2 w-fit">
                <Story />
            </div>
        ),
    ],
}
export default meta
type Story = StoryObj<typeof NavAppTooltip>
export const SQL: Story = { args: { item: { path: 'SQL editor', sceneKey: 'SQLEditor' } } }
export const Replay: Story = { args: { item: { path: 'Session replay', sceneKey: 'Replay' } } }
export const Group: Story = { args: { item: { path: 'Companies', iconType: 'group' } } }
export const Dark: Story = { ...SQL, globals: { theme: 'dark' } }
