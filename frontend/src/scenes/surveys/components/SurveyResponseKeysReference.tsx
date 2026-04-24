import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonCollapse } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { SurveyQuestion, SurveyQuestionType } from '~/types'

import { getSurveyIdBasedResponseKey } from '../utils'

export function SurveyResponseKeysReference({ questions }: { questions: SurveyQuestion[] }): JSX.Element | null {
    const applicableQuestions = questions
        .map((q, index) => ({ question: q, originalIndex: index }))
        .filter(({ question }) => question.type !== SurveyQuestionType.Link && question.id)
    const commonFields = [
        { label: 'Survey name', templateKey: "{event.properties['$survey_name']}" },
        { label: 'Survey ID', templateKey: "{event.properties['$survey_id']}" },
        { label: 'Respondent name', templateKey: '{person.name}' },
        { label: 'Respondent email', templateKey: '{person.properties.email}' },
    ]

    return (
        <LemonCollapse
            panels={[
                {
                    key: 'survey-keys',
                    header: 'Survey placeholders',
                    content: (
                        <div className="flex flex-col gap-1.5">
                            <p className="text-xs text-muted m-0">
                                Use these in notification message templates to include survey context and responses.
                            </p>
                            {commonFields.map(({ label, templateKey }) => (
                                <div
                                    key={label}
                                    className="flex items-center justify-between gap-2 rounded border p-1.5"
                                >
                                    <span className="text-xs truncate min-w-0">{label}</span>
                                    <LemonButton
                                        size="xsmall"
                                        type="secondary"
                                        icon={<IconCopy />}
                                        onClick={() => void copyToClipboard(templateKey, label.toLowerCase())}
                                        tooltip={templateKey}
                                        noPadding
                                        className="shrink-0 p-0.5"
                                    />
                                </div>
                            ))}
                            {applicableQuestions.map(({ question, originalIndex }) => {
                                const templateKey = `{event.properties['${getSurveyIdBasedResponseKey(question.id!)}']}`
                                return (
                                    <div
                                        key={question.id}
                                        className="flex items-center justify-between gap-2 rounded border p-1.5"
                                    >
                                        <span className="text-xs truncate min-w-0">
                                            Q{originalIndex + 1}: {question.question}
                                        </span>
                                        <LemonButton
                                            size="xsmall"
                                            type="secondary"
                                            icon={<IconCopy />}
                                            onClick={() => void copyToClipboard(templateKey, 'response key')}
                                            tooltip={templateKey}
                                            noPadding
                                            className="shrink-0 p-0.5"
                                        />
                                    </div>
                                )
                            })}
                        </div>
                    ),
                },
            ]}
        />
    )
}
