import { useValues } from 'kea'
import { MultipleChoiceQuestionViz } from 'scenes/surveys/components/question-visualizations/MultipleChoiceQuestionViz'
import { OpenQuestionViz } from 'scenes/surveys/components/question-visualizations/OpenQuestionViz'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

import { SurveyQuestion, SurveyQuestionType } from '~/types'

import { RatingQuestionViz } from './RatingQuestionViz'
import { SingleChoiceQuestionViz } from './SingleChoiceQuestionViz'

/**
 * SurveyQuestionVisualization is a smart component that renders the appropriate
 * visualization based on the question type.
 *
 * It uses the optimized data loading approach that makes a single API query for all questions.
 */

interface Props {
    question: SurveyQuestion
    questionIndex: number
}

export function SurveyQuestionVisualization({ question, questionIndex }: Props): JSX.Element | null {
    const { consolidatedSurveyResults, consolidatedSurveyResultsLoading } = useValues(surveyLogic)

    if (!question.id || question.type === SurveyQuestionType.Link) {
        return null
    }

    if (consolidatedSurveyResultsLoading) {
        return <div>loading surveys data</div>
    }

    const processedData = consolidatedSurveyResults?.responsesByQuestion[question.id]

    if (!processedData || processedData.total === 0) {
        return <div>No responses yet in survey question viz</div>
    }

    switch (question.type) {
        case SurveyQuestionType.Rating:
            return <RatingQuestionViz question={question} questionIndex={questionIndex} processedData={processedData} />
        case SurveyQuestionType.SingleChoice:
            return (
                <SingleChoiceQuestionViz
                    question={question}
                    questionIndex={questionIndex}
                    processedData={processedData}
                />
            )
        case SurveyQuestionType.MultipleChoice:
            return (
                <MultipleChoiceQuestionViz
                    question={question}
                    questionIndex={questionIndex}
                    processedData={processedData}
                />
            )
        case SurveyQuestionType.Open:
            return <OpenQuestionViz question={question} questionIndex={questionIndex} processedData={processedData} />
        default:
            return null
    }
}
