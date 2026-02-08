import { IconCheck } from '@posthog/icons'

import { MultiQuestionForm as MultiQuestionFormType } from '~/queries/schema/schema-assistant-messages'

import { MessageTemplate } from './MessageTemplate'

interface MultiQuestionFormRecapProps {
    form: MultiQuestionFormType
    /** Saved answers from the backend (used when the form was previously submitted and page is reloaded) */
    savedAnswers?: Record<string, string>
}

/**
 * Displays a completed multi-question form recap in the chat thread.
 * The interactive form is handled by MultiQuestionFormInput in InputFormArea.tsx.
 */
export function MultiQuestionFormRecap({ form, savedAnswers }: MultiQuestionFormRecapProps): JSX.Element | null {
    const questions = form.questions

    if (!questions || questions.length === 0) {
        return null
    }

    return (
        <MessageTemplate type="ai">
            <div className="flex flex-col gap-2">
                <div className="flex items-center gap-1.5 text-xs text-muted">
                    <IconCheck className="text-success" />
                    <span>Form submitted</span>
                </div>
                <div className="flex flex-col gap-1.5">
                    {questions.map((question) => (
                        <div key={question.id} className="text-sm">
                            <span className="text-muted">{question.question}</span>
                            <br />
                            <span className="font-medium">{savedAnswers?.[question.id] || '—'}</span>
                        </div>
                    ))}
                </div>
            </div>
        </MessageTemplate>
    )
}
