import { IconAI } from '@posthog/icons'

import {
    extractSandboxQuestionAnswer,
    parseSandboxQuestionAnswers,
    parseSandboxQuestions,
} from '../sandboxQuestionUtils'
import { GenericMcpToolRenderer } from './components/tool/GenericMcpToolRenderer'
import { SandboxToolRow } from './components/tool/SandboxToolRow'
import { resolveToolRowChrome } from './components/tool/toolRowShared'
import type { SandboxToolRendererProps } from './sandboxToolRegistry'

/**
 * Thread recap for the `AskUserQuestion` Claude built-in. The interactive answering happens in the
 * input overlay (`SandboxQuestionInput`); this is the compact transcript record. Once answered it
 * shows the question text and the chosen answer in the expanded card body. Malformed input falls back
 * to the generic tool card.
 */
export function SandboxQuestionRenderer(props: SandboxToolRendererProps): JSX.Element {
    const { message, icon, displayName } = props
    const questions = parseSandboxQuestions(message.rawInput)

    if (questions.length === 0) {
        return <GenericMcpToolRenderer {...props} />
    }

    const chrome = resolveToolRowChrome(props)
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

    const content =
        answered.length > 0 ? (
            <div className="flex flex-col gap-3">
                {answered.map((entry, index) => (
                    <div key={index} className="flex flex-col gap-1 text-[13px]">
                        <div className="text-muted">{entry.question}</div>
                        <span className="font-medium text-secondary">{entry.answer}</span>
                    </div>
                ))}
            </div>
        ) : undefined

    return (
        <SandboxToolRow
            icon={icon ?? <IconAI />}
            isLoading={chrome.isLoading}
            isFailed={chrome.isFailed}
            wasCancelled={chrome.wasCancelled}
            errorMessage={chrome.errorMessage}
            defaultOpen
            content={content}
            debugDetails={chrome.debugDetails}
        >
            {message.title || displayName || 'Question'}
        </SandboxToolRow>
    )
}
