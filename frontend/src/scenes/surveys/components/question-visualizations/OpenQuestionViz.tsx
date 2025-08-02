import { ResponseSummariesDisplay } from 'scenes/surveys/components/question-visualizations/OpenQuestionSummarizer'
import { ResponseCard } from 'scenes/surveys/components/question-visualizations/ResponseCard'
import { OpenQuestionResponseData } from 'scenes/surveys/surveyLogic'

import { BasicSurveyQuestion } from '~/types'

interface Props {
    question: BasicSurveyQuestion
    responseData: OpenQuestionResponseData[]
}

export function OpenQuestionViz({ question, responseData }: Props): JSX.Element | null {
    return (
        <div className="space-y-4">
            <ResponseSummariesDisplay />
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                {responseData.slice(0, 20).map((event, i) => (
                    <ResponseCard
                        key={`${question.id}-${i}`}
                        response={event.response}
                        distinctId={event.distinctId}
                        personProperties={event.personProperties}
                        timestamp={event.timestamp}
                    />
                ))}
                {responseData.length > 20 && (
                    <div className="border rounded p-3 bg-surface-primary flex items-center justify-center text-sm text-muted-foreground hover:bg-surface-secondary cursor-pointer transition-colors">
                        <div className="text-center">
                            <div className="font-medium">+{responseData.length - 20} more responses</div>
                            <div className="text-xs mt-1">Check all of them in the table below</div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}
