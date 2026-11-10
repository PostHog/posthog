import type { Meta, StoryObj } from '@storybook/react'

import { withWidth } from '../../redesign/trace/storyFixtures'
import { EvaluationSentence } from './EvaluationSentence'
import { NARROW_PANEL_WIDTH, PANEL_WIDTH, STORY_HOG, STORY_JUDGE, STORY_STEPS } from './previewStoryFixtures'

const meta: Meta<typeof EvaluationSentence> = {
    title: 'Scenes-App/AI observability/New evaluation/Sentence',
    component: EvaluationSentence,
    decorators: [withWidth(PANEL_WIDTH)],
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        evaluation: STORY_JUDGE,
        usesDecisionModel: false,
        model: 'GPT-5 mini',
        reports: 'a report every 100 results',
        steps: STORY_STEPS,
        currentIndex: 3,
        missing: {},
        onOpen: () => {},
    },
}
export default meta

type Story = StoryObj<typeof EvaluationSentence>

export const Judge: Story = {}
export const MissingCode: Story = {
    args: { evaluation: STORY_HOG, missing: { criteria: 'Add the Hog code that returns the result' } },
}
export const Narrow: Story = { decorators: [withWidth(NARROW_PANEL_WIDTH)] }
