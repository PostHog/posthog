import { IconCheck, IconX } from '@posthog/icons'

import { MultiQuestionForm as MultiQuestionFormType } from '~/queries/schema/schema-assistant-messages'

import { MessageTemplate } from './MessageTemplate'

interface MultiQuestionFormRecapProps {
    form: MultiQuestionFormType
    /** Saved answers from the backend (used when the form was previously submitted and page is reloaded) */
    savedAnswers?: Record<string, string | string[]>
    formStatus?: string
}

/**
 * Displays a completed multi-question form recap in the chat thread.
 * The interactive form is handled by MultiQuestionFormInput in InputFormArea.tsx.
 */
export function MultiQuestionFormRecap({
    form,
    savedAnswers,
    formStatus,
}: MultiQuestionFormRecapProps): JSX.Element | null {
    const questions = form.questions

    if (!questions || questions.length === 0) {
        return null
    }

    if (formStatus === 'dismiss_form') {
        return (
            <MessageTemplate type="ai">
                <div className="flex flex-col gap-2">
                    <div className="flex items-center gap-1.5 text-xs text-muted">
                        <IconX />
                        <span>Form dismissed</span>
                    </div>
                    <div className="text-sm text-muted">The user chose not to answer these questions.</div>
                </div>
            </MessageTemplate>
        )
    }

    return (
        <MessageTemplate type="ai">
            <div className="flex flex-col gap-2">
                <div className="flex items-center gap-1.5 text-xs text-muted">
                    <IconCheck className="text-success" />
                    <span>Form submitted</span>
                </div>
                <div className="flex flex-col gap-1.5">
                    {questions.map((question) => {
                        const hasFields = question.fields && question.fields.length > 0
                        return (
                            <div key={question.id} className="text-sm">
                                <span className="text-muted">{question.question}</span>
                                {hasFields ? (
                                    <div className="ml-3 mt-0.5 flex flex-col gap-0.5">
                                        {question.fields!.map((field) => {
                                            const answer = savedAnswers?.[field.id]
                                            return (
                                                <div key={field.id}>
                                                    <span className="text-muted">{field.label}:</span>{' '}
                                                    <span className="font-medium">
                                                        {answer
                                                            ? Array.isArray(answer)
                                                                ? answer.join(', ')
                                                                : answer
                                                            : savedAnswers
                                                              ? 'Skipped'
                                                              : '—'}
                                                    </span>
                                                </div>
                                            )
                                        })}
                                    </div>
                                ) : (
                                    <>
                                        <br />
                                        <span className="font-medium">
                                            {(() => {
                                                const answer = savedAnswers?.[question.id]
                                                if (!answer) {
                                                    return savedAnswers ? 'Skipped' : '—'
                                                }
                                                return Array.isArray(answer) ? answer.join(', ') : answer
                                            })()}
                                        </span>
                                    </>
                                )}
                            </div>
                        )
                    })}
                </div>
            </div>
        </MessageTemplate>
    )
}
