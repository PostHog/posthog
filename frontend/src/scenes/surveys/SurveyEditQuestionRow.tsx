import './EditSurvey.scss'

import { DraggableSyntheticListeners } from '@dnd-kit/core'
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDialog, LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Group } from 'kea-forms'
import { SortableDragIcon } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { Survey, SurveyQuestionType } from '~/types'

import { defaultSurveyFieldValues, NewSurvey, SurveyQuestionLabel } from './constants'
import { QuestionBranchingInput } from './QuestionBranchingInput'
import { HTMLEditor } from './SurveyAppearanceUtils'
import { surveyLogic } from './surveyLogic'

type SurveyQuestionHeaderProps = {
    index: number
    survey: Survey | NewSurvey
    setSelectedPageIndex: (index: number) => void
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
    setSelectedPageIndex,
    setSurveyValue,
}: SurveyQuestionHeaderProps): JSX.Element {
    const { hasBranchingLogic } = useValues(surveyLogic)
    const { deleteBranchingLogic } = useActions(surveyLogic)
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
                        const deleteQuestion = (): void => {
                            e.stopPropagation()
                            setSelectedPageIndex(index <= 0 ? 0 : index - 1)
                            setSurveyValue(
                                'questions',
                                survey.questions.filter((_, i) => i !== index)
                            )
                        }

                        if (hasBranchingLogic) {
                            LemonDialog.open({
                                title: 'Your survey has active branching logic',
                                description: (
                                    <p className="py-2">
                                        Deleting the question will remove your branching logic. Are you sure you want to
                                        continue?
                                    </p>
                                ),
                                primaryButton: {
                                    children: 'Continue',
                                    status: 'danger',
                                    onClick: () => {
                                        deleteBranchingLogic()
                                        deleteQuestion()
                                    },
                                },
                                secondaryButton: {
                                    children: 'Cancel',
                                },
                            })
                        } else {
                            deleteQuestion()
                        }
                    }}
                    tooltipPlacement="top-end"
                />
            )}
        </div>
    )
}

export function SurveyEditQuestionGroup({ index, question }: { index: number; question: any }): JSX.Element {
    const { survey, descriptionContentType } = useValues(surveyLogic)
    const { setDefaultForQuestionType, setSurveyValue, resetBranchingForQuestion } = useActions(surveyLogic)

    const initialDescriptionContentType = descriptionContentType(index) ?? 'text'

    const handleQuestionValueChange = (key: string, val: string): void => {
        const updatedQuestion = survey.questions.map((question, idx) => {
            if (index === idx) {
                return {
                    ...question,
                    [key]: val,
                }
            }
            return question
        })
        setSurveyValue('questions', updatedQuestion)
    }

    const handleTabChange = (key: string): void => {
        handleQuestionValueChange('descriptionContentType', key)
    }

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
                                survey.appearance?.thankYouMessageHeader
                            setDefaultForQuestionType(
                                index,
                                newType,
                                editingQuestion,
                                editingDescription,
                                editingThankYouMessage
                            )
                            resetBranchingForQuestion(index)
                        }}
                        options={[
                            {
                                label: SurveyQuestionLabel[SurveyQuestionType.Open],
                                value: SurveyQuestionType.Open,
                                'data-attr': `survey-question-type-${index}-${SurveyQuestionType.Open}`,
                            },
                            {
                                label: 'Link/Notification',
                                value: SurveyQuestionType.Link,
                                'data-attr': `survey-question-type-${index}-${SurveyQuestionType.Link}`,
                            },
                            {
                                label: 'Rating',
                                value: SurveyQuestionType.Rating,
                                'data-attr': `survey-question-type-${index}-${SurveyQuestionType.Rating}`,
                            },
                            ...[
                                {
                                    label: 'Single choice select',
                                    value: SurveyQuestionType.SingleChoice,
                                    'data-attr': `survey-question-type-${index}-${SurveyQuestionType.SingleChoice}`,
                                },
                                {
                                    label: 'Multiple choice select',
                                    value: SurveyQuestionType.MultipleChoice,
                                    'data-attr': `survey-question-type-${index}-${SurveyQuestionType.MultipleChoice}`,
                                },
                            ],
                        ]}
                    />
                </LemonField>
                <LemonField name="question" label="Label">
                    <LemonInput data-attr={`survey-question-label-${index}`} value={question.question} />
                </LemonField>
                <LemonField name="description" label="Description (optional)">
                    {({ value, onChange }) => (
                        <HTMLEditor
                            value={value}
                            onChange={(val) => {
                                onChange(val)
                                handleQuestionValueChange('description', val)
                            }}
                            onTabChange={handleTabChange}
                            activeTab={initialDescriptionContentType}
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
                                        setSurveyValue(
                                            'appearance.ratingButtonColor',
                                            val === 'emoji' ? '#939393' : 'white'
                                        )
                                        resetBranchingForQuestion(index)
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
                                        ...(question.display === 'number'
                                            ? [
                                                  { label: '1 - 7 (7 Point Likert Scale)', value: 7 },
                                                  { label: '0 - 10 (Net Promoter Score)', value: 10 },
                                              ]
                                            : []),
                                    ]}
                                    onChange={(val) => {
                                        const newQuestion = { ...survey.questions[index], scale: val }
                                        const newQuestions = [...survey.questions]
                                        newQuestions[index] = newQuestion
                                        setSurveyValue('questions', newQuestions)
                                        resetBranchingForQuestion(index)
                                    }}
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
                                                        <LemonField name="shuffleOptions" className="mt-2">
                                                            {({
                                                                value: shuffleOptions,
                                                                onChange: toggleShuffleOptions,
                                                            }) => (
                                                                <LemonCheckbox
                                                                    checked={!!shuffleOptions}
                                                                    label="Shuffle options"
                                                                    onChange={(checked) =>
                                                                        toggleShuffleOptions(checked)
                                                                    }
                                                                />
                                                            )}
                                                        </LemonField>
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
                            question.buttonText === undefined
                                ? survey.appearance?.submitButtonText ?? 'Submit'
                                : question.buttonText
                        }
                    />
                </LemonField>
                <QuestionBranchingInput questionIndex={index} question={question} />
            </div>
        </Group>
    )
}
