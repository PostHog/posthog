import type { Meta, StoryObj } from '@storybook/react'

import { TaggersDeprecationBanner } from './TaggersDeprecationBanner'

const meta: Meta<typeof TaggersDeprecationBanner> = {
    title: 'Scenes-App/LLM observability/Taggers deprecation banner',
    component: TaggersDeprecationBanner,
    parameters: {
        viewMode: 'story',
    },
}
export default meta

type Story = StoryObj<typeof TaggersDeprecationBanner>

export const Default: Story = {}

export const TaggerMigrated: Story = { args: { migratedToEvaluationId: '0190b1f2-0000-0000-0000-000000000001' } }

export const SomeTaggersMigrated: Story = { args: { someMigrated: true } }
