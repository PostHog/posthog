import { Meta, StoryObj } from '@storybook/react'

import { CommandKSearchNotice } from './CommandKSearchNotice'

const meta: Meta<typeof CommandKSearchNotice> = {
    title: 'Components/Command K search/Notice',
    component: CommandKSearchNotice,
    decorators: [
        (Story) => (
            <div data-quill className="w-160 bg-card p-1">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof CommandKSearchNotice>

export const DroppedWords: Story = {
    args: { row: { kind: 'notice', key: 'notice/partial', reason: 'partial', missing: ['xyzzy'], shown: ['report'] } },
}

export const CloseSpellings: Story = {
    args: { row: { kind: 'notice', key: 'notice/typos', reason: 'typos', missing: ['dashbord'], shown: ['dashbord'] } },
}
