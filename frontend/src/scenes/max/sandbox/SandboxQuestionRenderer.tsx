import { IconAI } from '@posthog/icons'

import { SandboxToolActivity } from '../components/Activity'
import { FallbackMcpToolRenderer } from '../messages/FallbackMcpToolRenderer'
import {
    extractSandboxQuestionAnswer,
    parseSandboxQuestionAnswers,
    parseSandboxQuestions,
} from '../sandboxQuestionUtils'
import type { SandboxToolRendererProps } from './sandboxToolRegistry'

/**
 * Thread recap for the `AskUserQuestion` Claude built-in. The interactive answering happens in the
 * input overlay (`SandboxQuestionInput`); this is the compact transcript record. While a question is
 * still being asked it contributes nothing here (no recap row) — the overlay owns the unanswered state.
 * Once answered it shows only the question text and the chosen answer; the "answered" tick lives in the
 * header `StatusBadge`, and the per-question header label is dropped to keep the recap quiet. Malformed
 * input falls back to the generic tool card.
 */
export function SandboxQuestionRenderer(props: SandboxToolRendererProps): JSX.Element {
    const { message, icon, displayName } = props
    const questions = parseSandboxQuestions(message.rawInput)

    if (questions.length === 0) {
        return <FallbackMcpToolRenderer {...props} />
    }

    const answersByKey = parseSandboxQuestionAnswers(message.rawOutput)
    // When the result didn't carry a per-question map, fall back to a single joined answer string
    // (Twig's `extractAnswer`) attributed to the first question, so the answer is never lost.
    const fallbackAnswer =
        Object.keys(answersByKey).length === 0 ? extractSandboxQuestionAnswer(message.rawOutput) : null

    const answered = questions
        .map((question, index) => {
            const answer = answersByKey[question.question] ?? (index === 0 ? fallbackAnswer : null)
            return answer ? { question: question.question, answer } : null
        })
        .filter((entry): entry is { question: string; answer: string } => entry !== null)

    const errorMessage = message.status === 'failed' ? message.error?.message : undefined
    const hasBody = answered.length > 0 || Boolean(errorMessage)

    return (
        <SandboxToolActivity
            message={message}
            icon={icon ?? <IconAI className="text-base" />}
            displayName={displayName}
        >
            {hasBody ? (
                <div className="flex flex-col gap-3">
                    {errorMessage && <div className="text-danger text-sm">{errorMessage}</div>}
                    {answered.map((entry, index) => (
                        <div key={index} className="flex flex-col gap-1 text-sm">
                            <div className="text-muted">{entry.question}</div>
                            <span className="font-medium">{entry.answer}</span>
                        </div>
                    ))}
                </div>
            ) : null}
        </SandboxToolActivity>
    )
}
