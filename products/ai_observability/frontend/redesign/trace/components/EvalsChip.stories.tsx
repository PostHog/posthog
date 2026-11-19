import type { Meta, StoryObj } from '@storybook/react'

import { FIXTURE_EVALS_SUMMARY } from '../storyFixtures'
import { EvalsChip } from './EvalsChip'

const meta: Meta<typeof EvalsChip> = {
    title: 'Scenes-App/AI observability/Trace view/Evals chip',
    component: EvalsChip,
    args: { onClick: () => {} },
}
export default meta

type Story = StoryObj<typeof EvalsChip>

export const SomeFailed: Story = { args: { summary: FIXTURE_EVALS_SUMMARY } }
export const AllPassed: Story = { args: { summary: { passed: 5, failed: 0, unrated: 0, nodes: [] } } }
export const OnlyUnrated: Story = { args: { summary: { passed: 0, failed: 0, unrated: 3, nodes: [] } } }
