import { SurveyQuestion } from '~/types'

export function OpenTextResponse({ value, question }: { value: unknown; question: SurveyQuestion }): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            {question.question && <span className="text-xs text-muted">{question.question}</span>}
            <blockquote className="border-l-2 border-border pl-3 text-sm text-primary italic">
                {String(value)}
            </blockquote>
        </div>
    )
}
