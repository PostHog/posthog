import { useValues } from 'kea'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

import { SurveyQuestionType } from '~/types'

import { RatingQuestionViz } from './RatingQuestionViz'
import { SingleChoiceQuestionViz } from './SingleChoiceQuestionViz'

/**
 * SurveyQuestionVisualization is a smart component that renders the appropriate
 * visualization based on the question type.
 *
 * It uses the optimized data loading approach that makes a single API query for all questions.
 */
export function SurveyQuestionVisualization({ questionIndex }: { questionIndex: number }): JSX.Element | null {
    const { survey } = useValues(surveyLogic)

    if (questionIndex >= survey.questions.length) {
        return <div>Question index out of range</div>
    }

    const question = survey.questions[questionIndex]

    switch (question.type) {
        case SurveyQuestionType.Rating:
            return <RatingQuestionViz questionIndex={questionIndex} />
        case SurveyQuestionType.SingleChoice:
            return <SingleChoiceQuestionViz questionIndex={questionIndex} />
        // other types are not implemented atm. link types dont have visualizations
        case SurveyQuestionType.Link:
        default:
            return null
    }
}
