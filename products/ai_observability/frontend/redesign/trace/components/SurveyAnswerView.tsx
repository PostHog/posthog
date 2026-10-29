import { SurveyAnswer } from '../types'
import { SurveyAnswerValue } from './SurveyAnswerValue'

export interface SurveyAnswerViewProps {
    answer: SurveyAnswer
}

export function SurveyAnswerView({ answer }: SurveyAnswerViewProps): JSX.Element {
    return (
        <div className="flex flex-col gap-0.5">
            <span className="text-xs text-secondary">{answer.question}</span>
            <SurveyAnswerValue answer={answer} />
        </div>
    )
}
