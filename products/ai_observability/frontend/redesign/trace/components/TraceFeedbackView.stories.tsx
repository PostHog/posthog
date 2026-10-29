import type { Meta, StoryObj } from '@storybook/react'

import { FIXTURE_FEEDBACK_MODE, FIXTURE_FEEDBACK_MODE_WITH_SURVEYS, withWidth } from '../storyFixtures'
import { TraceFeedbackView } from './TraceFeedbackView'

const unfocused = {
    ...FIXTURE_FEEDBACK_MODE,
    scores: FIXTURE_FEEDBACK_MODE.scores.map((row) => ({ ...row, focused: false })),
    responses: FIXTURE_FEEDBACK_MODE.responses.map((item) => ({ ...item, focused: false })),
}

const meta: Meta<typeof TraceFeedbackView> = {
    title: 'Scenes-App/AI observability/Trace view/Feedback',
    component: TraceFeedbackView,
    args: { onSelectStep: () => {} },
    decorators: [withWidth(960)],
}
export default meta

type Story = StoryObj<typeof TraceFeedbackView>

export const ScoresAndText: Story = { args: { state: unfocused } }
export const FocusedOnAStep: Story = { args: { state: FIXTURE_FEEDBACK_MODE } }
export const ScoresOnly: Story = { args: { state: { ...unfocused, responses: [] } } }
export const WithSurveys: Story = { args: { state: FIXTURE_FEEDBACK_MODE_WITH_SURVEYS } }
export const Narrow: Story = { args: { state: FIXTURE_FEEDBACK_MODE_WITH_SURVEYS }, decorators: [withWidth(520)] }
export const Empty: Story = {
    args: { state: { status: 'ready', scores: [], responses: [], unanswered: [], surveysFailed: false } },
}
export const SurveyReadFailed: Story = { args: { state: { ...unfocused, responses: [], surveysFailed: true } } }
export const Loading: Story = {
    args: { state: { status: 'loading' } },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
export const LoadError: Story = { args: { state: { status: 'error' } } }
