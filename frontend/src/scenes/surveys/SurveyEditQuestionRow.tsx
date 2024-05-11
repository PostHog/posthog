import './EditSurvey.scss'

import { DraggableSyntheticListeners } from '@dnd-kit/core'
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Group } from 'kea-forms'
import { SortableDragIcon } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { Survey, SurveyQuestionType } from '~/types'

import { defaultSurveyFieldValues, NewSurvey, SurveyQuestionLabel } from './constants'
import { HTMLEditor } from './SurveyAppearanceUtils'
import { surveyLogic } from './surveyLogic'

type SurveyQuestionHeaderProps = {
    index: number
    survey: Survey | NewSurvey
    setSelectedQuestion: (index: number) => void
    setSurveyValue: (key: string, value: any) => void
}

const DragHandle = ({ listeners }: { listeners: DraggableSyntheticListeners | undefined }): JSX.Element => (
    <span className="SurveyQuestionDragHandle" {...listeners}>
        <SortableDragIcon />
    </span>
)

export function SurveyEditQuestionHeader({
    index,
    survey,
    setSelectedQuestion,
    setSurveyValue,
}: SurveyQuestionHeaderProps): JSX.Element {
    const { setNodeRef, attributes, transform, transition, listeners, isDragging } = useSortable({
        id: index.toString(),
    })

    const questionsStartElements = [
        survey.questions.length > 1 ? <DragHandle key={index} listeners={listeners} /> : null,
    ].filter(Boolean)

    return (
        <div
            className="flex flex-row w-full items-center justify-between"
            ref={setNodeRef}
            {...attributes}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                position: 'relative',
                zIndex: isDragging ? 1 : undefined,
                transform: CSS.Translate.toString(transform),
                transition,
            }}
        >
            <div className="flex flex-row gap-2 items-center">
                {questionsStartElements.length ? <div className="flex">{questionsStartElements}</div> : null}

                <b>
                    Question {index + 1}. {survey.questions[index].question}
                </b>
            </div>
            {survey.questions.length > 1 && (
                <LemonButton
                    icon={<IconTrash />}
                    data-attr={`delete-survey-question-${index}`}
                    onClick={(e) => {
                        e.stopPropagation()
                        setSelectedQuestion(index <= 0 ? 0 : index - 1)
                        setSurveyValue(
                            'questions',
                            survey.questions.filter((_, i) => i !== index)
                        )
                    }}
                    tooltipPlacement="top-end"
                />
            )}
        </div>
    )
}

export function SurveyEditQuestionGroup({ index, question }: { index: number; question: any }): JSX.Element {
    const { survey, writingHTMLDescription } = useValues(surveyLogic)
    const { setDefaultForQuestionType, setWritingHTMLDescription, setSurveyValue } = useActions(surveyLogic)
    return (
        <Group name={`questions.${index}`} key={index}>
            <div className="flex flex-col gap-2">
                <LemonField name="type" label="Question type" className="max-w-60">
                    <LemonSelect
                        data-attr={`survey-question-type-${index}`}
                        onSelect={(newType) => {
                            const editingQuestion =
                                defaultSurveyFieldValues[question.type].questions[0].question !== question.question
                            const editingDescription =
                                defaultSurveyFieldValues[question.type].questions[0].description !==
                                question.description
                            const editingThankYouMessage =
                                defaultSurveyFieldValues[question.type].appearance.thankYouMessageHeader !==
                                survey.appearance.thankYouMessageHeader
                            setDefaultForQuestionType(
                                index,
                                newType,
                                editingQuestion,
                                editingDescription,
                                editingThankYouMessage
                            )
                        }}
                        options={[
                            {
                                label: SurveyQuestionLabel[SurveyQuestionType.Open],
                                value: SurveyQuestionType.Open,
                            },
                            {
                                label: 'Link/Notification',
                                value: SurveyQuestionType.Link,
                            },
                            {
                                label: 'Rating',
                                value: SurveyQuestionType.Rating,
                            },
                            ...[
                                {
                                    label: 'Single choice select',
                                    value: SurveyQuestionType.SingleChoice,
                                },
                                {
                                    label: 'Multiple choice select',
                                    value: SurveyQuestionType.MultipleChoice,
                                },
                            ],
                        ]}
                    />
                </LemonField>
                <LemonField name="question" label="Label">
                    <LemonInput value={question.question} />
                </LemonField>
                <LemonField name="description" label="Description (optional)">
                    {({ value, onChange }) => (
                        <HTMLEditor
                            value={value}
                            onChange={onChange}
                            writingHTMLDescription={writingHTMLDescription}
                            setWritingHTMLDescription={setWritingHTMLDescription}
                        />
                    )}
                </LemonField>
                {survey.questions.length > 1 && (
                    <LemonField name="optional" className="my-2">
                        <LemonCheckbox label="Optional" checked={!!question.optional} />
                    </LemonField>
                )}
                {question.type === SurveyQuestionType.Link && (
                    <LemonField name="link" label="Link" info="Make sure to include https:// in the url.">
                        <LemonInput value={question.link || ''} placeholder="https://posthog.com" />
                    </LemonField>
                )}
                {question.type === SurveyQuestionType.Rating && (
                    <div className="flex flex-col gap-2">
                        <div className="flex flex-row gap-4">
                            <LemonField name="display" label="Display type" className="w-1/2">
                                <LemonSelect
                                    options={[
                                        { label: 'Number', value: 'number' },
                                        { label: 'Emoji', value: 'emoji' },
                                    ]}
                                    onChange={(val) => {
                                        const newQuestion = { ...survey.questions[index], display: val, scale: 5 }
                                        const newQuestions = [...survey.questions]
                                        newQuestions[index] = newQuestion
                                        setSurveyValue('questions', newQuestions)
                                    }}
                                />
                            </LemonField>
                            <LemonField name="scale" label="Scale" className="w-1/2">
                                <LemonSelect
                                    options={[
                                        ...(question.display === 'emoji' ? [{ label: '1 - 3', value: 3 }] : []),
                                        {
                                            label: '1 - 5',
                                            value: 5,
                                        },
                                        ...(question.display === 'number' ? [{ label: '0 - 10', value: 10 }] : []),
                                    ]}
                                />
                            </LemonField>
                        </div>
                        <div className="flex flex-row gap-4">
                            <LemonField name="lowerBoundLabel" label="Lower bound label" className="w-1/2">
                                <LemonInput value={question.lowerBoundLabel || ''} />
                            </LemonField>
                            <LemonField name="upperBoundLabel" label="Upper bound label" className="w-1/2">
                                <LemonInput value={question.upperBoundLabel || ''} />
                            </LemonField>
                        </div>
                    </div>
                )}
                {(question.type === SurveyQuestionType.SingleChoice ||
                    question.type === SurveyQuestionType.MultipleChoice) && (
                    <div className="flex flex-col gap-2">
                        <LemonField name="hasOpenChoice">
                            {({ value: hasOpenChoice, onChange: toggleHasOpenChoice }) => (
                                <LemonField name="choices" label="Choices">
                                    {({ value, onChange }) => (
                                        <div className="flex flex-col gap-2">
                                            {(value || []).map((choice: string, index: number) => {
                                                const isOpenChoice = hasOpenChoice && index === value?.length - 1
                                                return (
                                                    <div className="flex flex-row gap-2 relative" key={index}>
                                                        <LemonInput
                                                            value={choice}
                                                            fullWidth
                                                            onChange={(val) => {
                                                                const newChoices = [...value]
                                                                newChoices[index] = val
                                                                onChange(newChoices)
                                                            }}
                                                        />
                                                        {isOpenChoice && (
                                                            <span className="question-choice-open-ended-footer">
                                                                open-ended
                                                            </span>
                                                        )}
                                                        <LemonButton
                                                            icon={<IconTrash />}
                                                            size="small"
                                                            noPadding
                                                            onClick={() => {
                                                                const newChoices = [...value]
                                                                newChoices.splice(index, 1)
                                                                onChange(newChoices)
                                                                if (isOpenChoice) {
                                                                    toggleHasOpenChoice(false)
                                                                }
                                                            }}
                                                        />
                                                    </div>
                                                )
                                            })}
                                            <div className="w-fit flex flex-row flex-wrap gap-2">
                                                {(value || []).length < 6 && (
                                                    <>
                                                        <LemonButton
                                                            icon={<IconPlusSmall />}
                                                            type="secondary"
                                                            fullWidth={false}
                                                            onClick={() => {
                                                                if (!value) {
                                                                    onChange([''])
                                                                } else if (hasOpenChoice) {
                                                                    const newChoices = value.slice(0, -1)
                                                                    newChoices.push('')
                                                                    newChoices.push(value[value.length - 1])
                                                                    onChange(newChoices)
                                                                } else {
                                                                    onChange([...value, ''])
                                                                }
                                                            }}
                                                        >
                                                            Add choice
                                                        </LemonButton>
                                                        {!hasOpenChoice && (
                                                            <LemonButton
                                                                icon={<IconPlusSmall />}
                                                                type="secondary"
                                                                fullWidth={false}
                                                                onClick={() => {
                                                                    if (!value) {
                                                                        onChange(['Other'])
                                                                    } else {
                                                                        onChange([...value, 'Other'])
                                                                    }
                                                                    toggleHasOpenChoice(true)
                                                                }}
                                                            >
                                                                Add open-ended choice
                                                            </LemonButton>
                                                        )}
                                                    </>
                                                )}
                                            </div>
                                        </div>
                                    )}
                                </LemonField>
                            )}
                        </LemonField>
                    </div>
                )}
                <LemonField name="buttonText" label="Button text">
                    <LemonInput
                        value={
                            question.buttonText === undefined ? survey.appearance.submitButtonText : question.buttonText
                        }
                    />
                </LemonField>
            </div>
        </Group>
    )
}
