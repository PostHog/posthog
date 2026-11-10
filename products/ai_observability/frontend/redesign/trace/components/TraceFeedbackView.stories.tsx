import type { Meta, StoryObj } from '@storybook/react'

import { FIXTURE_FEEDBACK, FIXTURE_FEEDBACK_STEPS, FIXTURE_FEEDBACK_WITH_SURVEYS, withWidth } from '../storyFixtures'
import { TraceFeedbackView } from './TraceFeedbackView'

const meta: Meta<typeof TraceFeedbackView> = {
    title: 'Scenes-App/AI observability/Trace view/Feedback',
    component: TraceFeedbackView,
    args: { feedback: FIXTURE_FEEDBACK, failed: false, steps: FIXTURE_FEEDBACK_STEPS, onSelectStep: () => {} },
    decorators: [withWidth(960)],
}
export default meta

type Story = StoryObj<typeof TraceFeedbackView>

export const ScoresAndText: Story = {}
export const FocusedOnAStep: Story = { args: { steps: { ...FIXTURE_FEEDBACK_STEPS, focusNodeId: 'gen-answer' } } }
export const ScoresOnly: Story = { args: { feedback: { ...FIXTURE_FEEDBACK, responses: [] } } }
export const WithSurveys: Story = { args: { feedback: FIXTURE_FEEDBACK_WITH_SURVEYS } }
export const Narrow: Story = { args: { feedback: FIXTURE_FEEDBACK_WITH_SURVEYS }, decorators: [withWidth(520)] }
export const Empty: Story = { args: { feedback: { ...FIXTURE_FEEDBACK, scores: [], responses: [], unanswered: [] } } }
export const SurveyReadFailed: Story = {
    args: { feedback: { ...FIXTURE_FEEDBACK, responses: [], surveyResponsesStatus: 'failed' } },
}
export const Loading: Story = {
    args: { feedback: null },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
export const LoadError: Story = { args: { feedback: null, failed: true } }
