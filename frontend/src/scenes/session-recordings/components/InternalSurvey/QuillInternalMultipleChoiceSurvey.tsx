import { useId } from 'react'

import {
    Button,
    Card,
    CardContent,
    Checkbox,
    Field,
    FieldLabel,
    Heading,
    Item,
    ItemContent,
    ItemTitle,
    Text,
    Textarea,
} from '@posthog/quill'

import { Survey, SurveyQuestion, SurveyQuestionType } from '~/types'

import { QuillInternalSurveyHelpMessage } from './QuillInternalSurveyHelpMessage'

export function QuillInternalMultipleChoiceSurvey({
    survey,
    surveyResponse,
    showThankYouMessage,
    thankYouMessage,
    openChoice,
    onChoiceChange,
    onOpenChoiceChange,
    onSubmit,
    submitDisabledReason,
    showAskMax,
    askMaxDisabledReason,
    onAskMax,
    isHelpEnabled,
    helpTitles,
}: {
    survey: Survey
    surveyResponse: string[]
    showThankYouMessage: boolean
    thankYouMessage: string
    openChoice: string | null
    onChoiceChange: (choice: string, checked: boolean) => void
    onOpenChoiceChange: (openChoice: string) => void
    onSubmit: () => void
    submitDisabledReason: string | false
    showAskMax: boolean
    askMaxDisabledReason: string | false
    onAskMax: () => void
    isHelpEnabled: boolean
    helpTitles: string[]
}): JSX.Element {
    const idPrefix = useId()

    return (
        <div className="flex flex-wrap items-start gap-4">
            <Card size="sm" className="min-w-0 flex-1">
                <CardContent className="flex flex-col gap-4">
                    {survey.questions.map((question: SurveyQuestion) => (
                        <div key={question.question} className="flex flex-col gap-2">
                            {showThankYouMessage ? (
                                <Text size="xs" render={<p className="m-0" />}>
                                    {thankYouMessage}
                                </Text>
                            ) : (
                                <>
                                    <Text size="xs" weight="semibold" render={<p className="m-0" />}>
                                        {question.question}
                                    </Text>
                                    {question.type === SurveyQuestionType.MultipleChoice && (
                                        <div className="flex flex-col gap-2">
                                            {question.choices.map((choice, index) => {
                                                // Add an open choice text area if the last choice is an open choice
                                                if (index === question.choices.length - 1 && question.hasOpenChoice) {
                                                    return (
                                                        <Textarea
                                                            key={choice}
                                                            aria-label={choice}
                                                            placeholder="Please share any additional comments or feedback"
                                                            onChange={(event) => onOpenChoiceChange(event.target.value)}
                                                            value={openChoice ?? ''}
                                                            data-attr="replay-churn-open-choice-text"
                                                        />
                                                    )
                                                }

                                                const checkboxId = `${idPrefix}-${index}`

                                                return (
                                                    <Field key={choice} orientation="horizontal">
                                                        <Checkbox
                                                            id={checkboxId}
                                                            onCheckedChange={(checked) =>
                                                                onChoiceChange(choice, checked)
                                                            }
                                                            data-attr={`replay-churn-choice-${choice
                                                                .toLowerCase()
                                                                .replace(' ', '-')}`}
                                                        />
                                                        <FieldLabel htmlFor={checkboxId}>{choice}</FieldLabel>
                                                    </Field>
                                                )
                                            })}
                                        </div>
                                    )}
                                    <div className="flex flex-wrap gap-2">
                                        <Button
                                            data-attr="replay-survey-submit"
                                            variant="primary"
                                            disabledReason={submitDisabledReason}
                                            onClick={onSubmit}
                                        >
                                            {question.buttonText ?? 'Submit'}
                                        </Button>
                                        {showAskMax && (
                                            <Button
                                                data-attr="replay-survey-ask-max"
                                                disabledReason={askMaxDisabledReason}
                                                variant="outline"
                                                onClick={onAskMax}
                                            >
                                                Ask PostHog AI for help
                                            </Button>
                                        )}
                                    </div>
                                </>
                            )}
                        </div>
                    ))}
                </CardContent>
            </Card>
            {isHelpEnabled && (
                <div className="flex min-w-0 flex-1 flex-col gap-2">
                    {surveyResponse.length > 0 && (
                        <Heading size="sm" render={<h3 className="m-0" />}>
                            Here is how we can help you
                        </Heading>
                    )}
                    {helpTitles
                        .filter((title) => surveyResponse.includes(title))
                        .map((title) => (
                            <Item key={title} tone="info" size="sm">
                                <ItemContent>
                                    <ItemTitle>{title}</ItemTitle>
                                    <QuillInternalSurveyHelpMessage title={title} />
                                </ItemContent>
                            </Item>
                        ))}
                </div>
            )}
        </div>
    )
}
