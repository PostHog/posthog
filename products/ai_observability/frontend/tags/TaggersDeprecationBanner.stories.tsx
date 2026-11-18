import type { Meta, StoryObj } from '@storybook/react'

import { TaggersDeprecationBanner } from './TaggersDeprecationBanner'

const meta: Meta<typeof TaggersDeprecationBanner> = {
    title: 'Scenes-App/LLM observability/Taggers deprecation banner',
    component: TaggersDeprecationBanner,
    parameters: {
        viewMode: 'story',
    },
    // The banner is a size container, so without a width around it the snapshot shrinks it to a sliver.
    decorators: [(StoryFn): JSX.Element => <div className="w-[720px]">{StoryFn()}</div>],
}
export default meta

type Story = StoryObj<typeof TaggersDeprecationBanner>

export const Default: Story = {}

export const TaggerMigrated: Story = { args: { migratedToEvaluationId: '0190b1f2-0000-0000-0000-000000000001' } }

export const SomeTaggersMigrated: Story = { args: { someMigrated: true } }
