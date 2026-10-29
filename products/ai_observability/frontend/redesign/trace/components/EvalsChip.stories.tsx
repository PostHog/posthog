import type { Meta, StoryObj } from '@storybook/react'

import { FIXTURE_EVALS_CHIP } from '../storyFixtures'
import { EvalsChip } from './EvalsChip'

const meta: Meta<typeof EvalsChip> = {
    title: 'Scenes-App/AI observability/Trace view/Evals chip',
    component: EvalsChip,
    args: { onClick: () => {} },
}
export default meta

type Story = StoryObj<typeof EvalsChip>

export const SomeFailed: Story = { args: { chip: FIXTURE_EVALS_CHIP } }
export const AllPassed: Story = { args: { chip: { passed: 5, graded: 5, unrated: 0 } } }
export const OnlyUnrated: Story = { args: { chip: { passed: 0, graded: 0, unrated: 3 } } }
