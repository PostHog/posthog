import { IconAI } from '@posthog/icons'

import {
    extractSandboxQuestionAnswer,
    parseSandboxQuestionAnswers,
    parseSandboxQuestions,
} from '../sandboxQuestionUtils'
import { GenericMcpToolRenderer } from './components/tool/GenericMcpToolRenderer'
import { SandboxToolActivity } from './components/tool/SandboxToolActivity'
import type { SandboxToolRendererProps } from './sandboxToolRegistry'

/**
 * Thread recap for the `AskUserQuestion` Claude built-in. The interactive answering happens in the
 * input overlay (`SandboxQuestionInput`); this is the compact transcript record, shown always-visible
 * below the header once answered. Malformed input falls back to the generic tool card.
 */
export function SandboxQuestionRenderer(props: SandboxToolRendererProps): JSX.Element {
    const { message, icon, displayName, turnComplete, turnCancelled } = props
    const questions = parseSandboxQuestions(message.rawInput)

    if (questions.length === 0) {
        return <GenericMcpToolRenderer {...props} />
    }

    const answersByKey = parseSandboxQuestionAnswers(message.rawOutput)
    // When the result didn't carry a per-question map, fall back to a single joined answer string
    // (the agent's `extractAnswer`) attributed to the first question, so the answer is never lost.
    const fallbackAnswer =
        Object.keys(answersByKey).length === 0 ? extractSandboxQuestionAnswer(message.rawOutput) : null

    const answered = questions
        .map((question, index) => {
            const answer = answersByKey[question.question] ?? (index === 0 ? fallbackAnswer : null)
            return answer ? { question: question.question, answer } : null
        })
        .filter((entry): entry is { question: string; answer: string } => entry !== null)

    return (
        <SandboxToolActivity
            message={message}
            icon={icon ?? <IconAI />}
            title={message.title || displayName || 'Question'}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        >
            {answered.length > 0 && (
                <div className="flex flex-col gap-3">
                    {answered.map((entry, index) => (
                        <div key={index} className="flex flex-col gap-1 text-xs">
                            <div className="text-muted">{entry.question}</div>
                            <span className="font-medium text-secondary">{entry.answer}</span>
                        </div>
                    ))}
                </div>
            )}
        </SandboxToolActivity>
    )
}
