import { uuid } from 'lib/utils/dom'

import type { Message } from './llmPlaygroundPromptsLogic'

// The API caps mirror `MAX_DECISION_QUESTIONS` and `MAX_SCORE_LEVELS` in the proxy serializer.
export const MAX_DECISION_QUESTIONS = 20
export const MAX_SCORE_LEVELS = 10

export type PlaygroundQuestionType = 'noul' | 'choice' | 'score'

export interface PlaygroundQuestionOption {
    id: string
    name: string
    description: string
}

export interface PlaygroundQuestion {
    id: string
    type: PlaygroundQuestionType
    instructions: string
    options: PlaygroundQuestionOption[]
}

export interface PlaygroundDecisionAnswer {
    type: PlaygroundQuestionType | 'refusal'
    probability: number | null
    choice: string | null
    score: number | null
    confidence: number | null
    probabilities: Record<string, number> | null
}

export interface PlaygroundDecisionResult {
    model: string
    answers: Record<string, PlaygroundDecisionAnswer>
    input_tokens: number | null
    output_tokens: number | null
}

export interface DecisionQuestionPayload {
    type: PlaygroundQuestionType
    instructions: string
    options?: { name: string; description?: string }[]
}

/** Turns a conversation into System One input text, so a trace opened in the playground carries over. */
export function messagesToDecisionInput(messages: Message[]): string {
    return messages
        .filter((message) => message.content.trim())
        .map((message) => `${message.role}: ${message.content.trim()}`)
        .join('\n\n')
}

export function createPlaygroundQuestionOption(): PlaygroundQuestionOption {
    return { id: uuid(), name: '', description: '' }
}

export function createPlaygroundQuestion(type: PlaygroundQuestionType = 'noul'): PlaygroundQuestion {
    const levels = type === 'score' ? 2 : type === 'choice' ? 1 : 0
    return {
        id: uuid(),
        type,
        instructions: '',
        options: Array.from({ length: levels }, createPlaygroundQuestionOption),
    }
}

export function decisionQuestionsDisabledReason(questions: PlaygroundQuestion[]): string | null {
    if (questions.length === 0) {
        return 'Add a question to ask the model'
    }
    if (questions.length > MAX_DECISION_QUESTIONS) {
        return `Ask at most ${MAX_DECISION_QUESTIONS} questions at once`
    }
    for (const question of questions) {
        if (!question.instructions.trim()) {
            return 'Write every question before running'
        }
        const names = question.options.map((option) => option.name.trim())
        if (question.type !== 'noul' && names.some((name) => !name)) {
            return question.type === 'choice' ? 'Name every option' : 'Name every level of the scale'
        }
        if (new Set(names).size !== names.length) {
            return 'Give each option of a question a different name'
        }
        if (question.type === 'choice' && names.length < 1) {
            return 'A multiple choice question needs at least one option'
        }
        if (question.type === 'score' && (names.length < 2 || names.length > MAX_SCORE_LEVELS)) {
            return `A rating question needs 2 to ${MAX_SCORE_LEVELS} levels`
        }
    }
    return null
}

export function toDecisionQuestionsPayload(
    questions: PlaygroundQuestion[],
    resolve: (text: string) => string
): Record<string, DecisionQuestionPayload> {
    return Object.fromEntries(
        questions.map((question) => [
            question.id,
            {
                type: question.type,
                instructions: resolve(question.instructions.trim()),
                ...(question.type === 'noul'
                    ? {}
                    : {
                          options: question.options.map((option) => ({
                              name: option.name.trim(),
                              ...(question.type === 'choice' && option.description.trim()
                                  ? { description: option.description.trim() }
                                  : {}),
                          })),
                      }),
            },
        ])
    )
}
