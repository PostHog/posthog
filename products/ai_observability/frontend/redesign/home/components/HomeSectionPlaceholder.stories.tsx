import type { Meta, StoryObj } from '@storybook/react'

import { HomeSectionPlaceholder } from './HomeSectionPlaceholder'

const meta: Meta<typeof HomeSectionPlaceholder> = {
    title: 'Scenes-App/AI observability/Home/Section placeholder',
    component: HomeSectionPlaceholder,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { section: 'expensive-users', title: 'Most expensive users' },
}
export default meta

type Story = StoryObj<typeof HomeSectionPlaceholder>

export const Titled: Story = {}

export const WithSwitch: Story = {
    args: { section: 'to-review', title: 'To review', switchLabels: ['Sessions', 'Traces'] },
}

export const NarrowContainer: Story = {
    ...WithSwitch,
    decorators: [
        (StoryComponent) => (
            <div className="w-60">
                <StoryComponent />
            </div>
        ),
    ],
}
