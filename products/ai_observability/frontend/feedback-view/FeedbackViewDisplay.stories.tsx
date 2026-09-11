import type { Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { NEW_SURVEY } from 'scenes/surveys/constants'
import { teamLogic } from 'scenes/teamLogic'

import { useStorybookMocks } from '~/mocks/browser'
import { Survey, SurveyQuestionType, SurveyType } from '~/types'

import { aiObservabilityTraceLogic } from '../aiObservabilityTraceLogic'
import { FeedbackViewDisplay } from './FeedbackViewDisplay'
import { feedbackViewLogic } from './feedbackViewLogic'

const survey: Survey = {
    ...NEW_SURVEY,
    id: '0199ed4a-5c03-0000-3220-df21df612e95',
    name: 'AI response feedback',
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    type: SurveyType.API,
    questions: [
        {
            type: SurveyQuestionType.Rating,
            question: 'Was this response helpful?',
            display: 'emoji',
            scale: 2,
            lowerBoundLabel: '',
            upperBoundLabel: '',
        },
    ],
}

const meta: Meta<typeof FeedbackViewDisplay> = {
    title: 'Scenes-App/AI observability/Feedback',
    component: FeedbackViewDisplay,
    render: () => {
        const traceLogic = useMountedLogic(aiObservabilityTraceLogic)
        const feedbackLogic = useMountedLogic(feedbackViewLogic({ traceId: traceLogic.values.traceId }))
        useStorybookMocks({
            get: {
                '/api/projects/:team_id/surveys/': { results: [survey] },
            },
        })
        useOnMountEffect(() => {
            teamLogic.actions.loadCurrentTeamSuccess({ ...teamLogic.values.currentTeam!, surveys_opt_in: false })
            feedbackLogic.actions.loadSurveyEventsSuccess([
                {
                    id: 'example-feedback-event',
                    event: 'survey sent',
                    createdAt: '2026-01-01T00:00:00Z',
                    properties: {
                        $survey_id: survey.id,
                        $survey_response: 1,
                        $survey_completed: true,
                    },
                },
            ])
        })
        return <FeedbackViewDisplay />
    },
}
export default meta
type Story = StoryObj<typeof meta>

export const ApiFeedbackWithSurveysDisabled: Story = {}
