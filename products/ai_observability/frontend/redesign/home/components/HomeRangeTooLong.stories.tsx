import type { Meta, StoryObj } from '@storybook/react'

import { RANGE_TOO_LONG_DETAIL } from '../homeFixtures'
import { HomeRangeTooLong } from './HomeRangeTooLong'

const meta: Meta<typeof HomeRangeTooLong> = {
    title: 'Scenes-App/AI observability/Home/Range too long',
    component: HomeRangeTooLong,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { detail: RANGE_TOO_LONG_DETAIL },
}
export default meta

type Story = StoryObj<typeof HomeRangeTooLong>

export const Default: Story = {}

export const NarrowContainer: Story = {
    decorators: [
        (StoryComponent) => (
            <div className="w-60">
                <StoryComponent />
            </div>
        ),
    ],
}
