import type { Meta, StoryObj } from '@storybook/react'

import { withWidth } from '../../redesign/trace/storyFixtures'
import { EvaluationPastTrafficOption } from './EvaluationPastTrafficOption'
import { NARROW_PANEL_WIDTH } from './previewStoryFixtures'

const meta: Meta<typeof EvaluationPastTrafficOption> = {
    title: 'Scenes-App/AI observability/New evaluation/Past traffic option',
    component: EvaluationPastTrafficOption,
    decorators: [withWidth(NARROW_PANEL_WIDTH)],
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        checked: true,
        onChange: () => {},
        volume: { target: 'generation', matchingGenerations: 86, matchingUnits: 86, runs: 86 },
        callsJudge: true,
    },
}
export default meta

type Story = StoryObj<typeof EvaluationPastTrafficOption>

export const Offered: Story = {}
export const NothingToEvaluate: Story = {
    args: { volume: { target: 'generation', matchingGenerations: 86, matchingUnits: 86, runs: 0 } },
}
