import type { Meta, StoryObj } from '@storybook/react'

import { FolderNavigation } from './FolderNavigation'

const meta: Meta<typeof FolderNavigation> = {
    title: 'Layout/Folder navigation',
    component: FolderNavigation,
    args: { folder: 'Research/Customer interviews/Notes', onOpen: () => {} },
    decorators: [
        (Story) => (
            <div className="w-52">
                <Story />
            </div>
        ),
    ],
}
export default meta
type Story = StoryObj<typeof FolderNavigation>
export const Nested: Story = {}
export const Root: Story = { args: { folder: '' } }
export const LongName: Story = { args: { folder: 'Research/Customer interviews from the latest onboarding study' } }
