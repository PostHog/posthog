import { LemonTag } from '@posthog/lemon-ui'

import type { PlaygroundDecisionAnswer, PlaygroundDecisionResult, PlaygroundQuestion } from './playgroundDecisions'

function percent(value: number | null): string {
    return value === null ? '' : `${Math.round(value * 100)}%`
}

function AnswerSummary({
    answer,
    question,
}: {
    answer: PlaygroundDecisionAnswer | undefined
    question: PlaygroundQuestion
}): JSX.Element {
    if (!answer || answer.type === 'refusal') {
        return <LemonTag type="muted">Declined to answer</LemonTag>
    }
    if (answer.type === 'noul') {
        const yes = answer.probability ?? 0
        return (
            <div className="flex items-center gap-2">
                <LemonTag type={yes >= 0.5 ? 'success' : 'danger'}>{yes >= 0.5 ? 'Yes' : 'No'}</LemonTag>
                <span className="text-secondary">{percent(yes)} yes</span>
            </div>
        )
    }
    // Score probabilities are keyed by level index, so read them back as the level names.
    const labelOf = (key: string): string =>
        answer.type === 'score' ? (question.options[Number(key)]?.name.trim() ?? key) : key
    const ranked = Object.entries(answer.probabilities ?? {}).sort(([, a], [, b]) => b - a)
    const score = answer.score ?? 0
    return (
        <div className="flex flex-col gap-1">
            <div className="flex flex-wrap items-center gap-2">
                <LemonTag type="highlight">
                    {answer.type === 'choice' ? answer.choice : labelOf(String(Math.round(score)))}
                </LemonTag>
                {answer.type === 'score' && (
                    <span className="text-secondary">
                        {score.toFixed(2)} on a 0 to {question.options.length - 1} scale
                    </span>
                )}
                <span className="text-secondary">{percent(answer.confidence)} confidence</span>
            </div>
            <div className="text-secondary">
                {ranked.map(([key, probability]) => `${labelOf(key)} ${percent(probability)}`).join(' · ')}
            </div>
        </div>
    )
}

export function PlaygroundDecisionAnswers({
    questions,
    result,
}: {
    questions: PlaygroundQuestion[]
    result: PlaygroundDecisionResult
}): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            {questions.map((question) => (
                <div key={question.id} className="flex flex-col gap-1">
                    <div className="font-semibold">{question.instructions}</div>
                    <AnswerSummary answer={result.answers[question.id]} question={question} />
                </div>
            ))}
            <div className="text-secondary">Answered by {result.model}</div>
        </div>
    )
}
