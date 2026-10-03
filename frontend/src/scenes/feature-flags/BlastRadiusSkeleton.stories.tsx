import { Meta, StoryObj } from '@storybook/react'

import { BlastRadiusSkeleton } from './BlastRadiusSkeleton'

const meta: Meta<typeof BlastRadiusSkeleton> = {
    title: 'Scenes-App/Feature Flags/Blast Radius Skeleton',
    component: BlastRadiusSkeleton,
    args: { targetName: 'users' },
    parameters: {
        testOptions: {
            // The story's content is the loader itself, so the runner must not wait for it to disappear
            waitForLoadersToDisappear: false,
        },
    },
    decorators: [
        (Story) => (
            <div className="text-xs text-muted w-80">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof BlastRadiusSkeleton>

export const Default: Story = {}
