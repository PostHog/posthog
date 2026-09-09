import { Meta, StoryObj } from '@storybook/react'

import { NotebookRunProgressBanner } from './NotebookRunProgressBanner'

const meta: Meta<typeof NotebookRunProgressBanner> = {
    title: 'Scenes-App/Notebooks/Run progress banner',
    component: NotebookRunProgressBanner,
    args: { label: 'Running cell 3 of 8', onStop: () => {} },
    tags: ['autodocs'],
}
export default meta

type Story = StoryObj<typeof NotebookRunProgressBanner>

export const Running: Story = {}

export const Starting: Story = {
    args: { label: 'Starting the run' },
}

/** The scene a notebook actually gets with the nav and a side panel open, where the row must wrap rather than clip. */
export const NarrowScene: Story = {
    decorators: [
        (Story) => (
            <div className="w-[520px]">
                <Story />
            </div>
        ),
    ],
    args: { label: 'Running cell 12 of 40, with a long dataframe name in the plan' },
}
