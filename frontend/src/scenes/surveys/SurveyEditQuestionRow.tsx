import './EditSurvey.scss'

import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useActions, useValues } from 'kea'
import { Group } from 'kea-forms'

import { IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDialog, LemonInput, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { QuestionBranchingInput } from 'scenes/surveys/components/question-branching/QuestionBranchingInput'

import {
    MultipleSurveyQuestion,
    RatingSurveyQuestion,
    Survey,
    SurveyQuestion,
    SurveyQuestionType,
    SurveyType,
} from '~/types'

import { HTMLEditor } from './SurveyAppearanceUtils'
import { SurveyDragHandle } from './SurveyDragHandle'
import { NewSurvey, SCALE_OPTIONS, SURVEY_RATING_SCALE, SurveyQuestionLabel } from './constants'
import { surveyLogic } from './surveyLogic'

type SurveyQuestionHeaderProps = {
    index: number
    survey: Survey | NewSurvey
    setSelectedPageIndex: (index: number) => void
    setSurveyValue: (key: string, value: any) => void
}

const MAX_NUMBER_OF_OPTIONS = 15

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

    return (
        <div
            className="flex flex-row w-full items-center justify-between relative"
            ref={setNodeRef}
            {...attributes}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                zIndex: isDragging ? 1 : undefined,
                transform: CSS.Translate.toString(transform),
                transition,
            }}
        >
            <div className="flex flex-row gap-2 items-center">
                <SurveyDragHandle listeners={listeners} hasMultipleQuestions={survey.questions.length > 1} />

                <b>
                    Question {index + 1}. {survey.questions[index].question}
                </b>
            </div>
            {survey.questions.length > 1 && (
                <LemonButton
                    icon={<IconTrash />}
                    size="xsmall"
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

function canQuestionSkipSubmitButton(
    question: SurveyQuestion
): question is RatingSurveyQuestion | MultipleSurveyQuestion {
    return (
        question.type === SurveyQuestionType.Rating ||
        (question.type === SurveyQuestionType.SingleChoice && !question.hasOpenChoice)
    )
}

export function SurveyEditQuestionGroup({ index, question }: { index: number; question: SurveyQuestion }): JSX.Element {
    const { survey, descriptionContentType } = useValues(surveyLogic)
    const { setDefaultForQuestionType, setSurveyValue, resetBranchingForQuestion, setMultipleSurveyQuestion } =
        useActions(surveyLogic)

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

    const canSkipSubmitButton = canQuestionSkipSubmitButton(question)

    const confirmQuestionTypeChange = (
        index: number,
        question: MultipleSurveyQuestion,
        newType: SurveyQuestionType
    ): void => {
        // Reset to current type first (because onSelect has already changed it)
        setMultipleSurveyQuestion(index, question, question.type)

        LemonDialog.open({
            title: 'Changing question type',
            description: (
                <p className="py-2">The choices you have configured will be removed. Would you like to proceed?</p>
            ),
            primaryButton: {
                children: 'Continue',
                status: 'danger',
                onClick: () => {
                    setDefaultForQuestionType(index, question, newType)
                    resetBranchingForQuestion(index)
                },
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    return (
        <Group name={`questions.${index}`} key={index}>
            <div className="flex flex-col gap-2">
                <LemonField name="type" label="Question type" className="max-w-60">
                    <LemonSelect
                        data-attr={`survey-question-type-${index}`}
                        onSelect={(newType) => {
                            const isCurrentMultipleChoice =
                                question.type === SurveyQuestionType.MultipleChoice ||
                                question.type === SurveyQuestionType.SingleChoice
                            const isNewMultipleChoice =
                                newType === SurveyQuestionType.MultipleChoice ||
                                newType === SurveyQuestionType.SingleChoice

                            // Same multiple choice type - just update type
                            if (isCurrentMultipleChoice && isNewMultipleChoice) {
                                setMultipleSurveyQuestion(index, question, newType)
                                resetBranchingForQuestion(index)
                                return
                            }
                            if (isCurrentMultipleChoice && !isNewMultipleChoice) {
                                confirmQuestionTypeChange(index, question, newType)
                                return
                            }
                            setDefaultForQuestionType(index, question, newType)
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
                    <LemonField name="link" label="Link" info="Only https:// or mailto: links are supported.">
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
                                        const newQuestion = {
                                            ...survey.questions[index],
                                            display: val,
                                            scale: SURVEY_RATING_SCALE.LIKERT_5_POINT,
                                        }
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
                                    options={question.display === 'emoji' ? SCALE_OPTIONS.EMOJI : SCALE_OPTIONS.NUMBER}
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
                                                            suffix={
                                                                isOpenChoice && (
                                                                    <LemonTag type="highlight">open-ended</LemonTag>
                                                                )
                                                            }
                                                        />
                                                        <LemonButton
                                                            icon={<IconTrash />}
                                                            size="xsmall"
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
                                                {((value || []).length < MAX_NUMBER_OF_OPTIONS ||
                                                    survey.type != SurveyType.Popover) && (
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
                <LemonField
                    name="buttonText"
                    label="Submit button text"
                    className="flex-1 flex gap-1 justify-center"
                    info={
                        canSkipSubmitButton
                            ? "When the 'Automatically submit on selection' option is enabled, users won't need to click a submit button - their response will be submitted immediately after selecting an option. The submit button will be hidden. Requires at least version 1.244.0 of posthog-js. Not available for the mobile SDKs at the moment."
                            : undefined
                    }
                >
                    <>
                        {(!canSkipSubmitButton || (canSkipSubmitButton && !question.skipSubmitButton)) && (
                            <LemonInput
                                value={
                                    question.buttonText === undefined
                                        ? (survey.appearance?.submitButtonText ?? 'Submit')
                                        : question.buttonText
                                }
                                onChange={(val) => handleQuestionValueChange('buttonText', val)}
                            />
                        )}
                        {canSkipSubmitButton && (
                            <LemonField
                                name="skipSubmitButton"
                                info={
                                    <>
                                        If enabled, the survey will submit immediately after the user makes a selection
                                        (for single-choice without open-ended, or rating questions), and the submit
                                        button will be hidden/text ignored.
                                    </>
                                }
                            >
                                {({ value: skipSubmitButtonValue, onChange: onSkipSubmitButtonChange }) => (
                                    <LemonCheckbox
                                        label="Automatically submit on selection"
                                        checked={!!skipSubmitButtonValue}
                                        onChange={onSkipSubmitButtonChange}
                                    />
                                )}
                            </LemonField>
                        )}
                    </>
                </LemonField>
                <QuestionBranchingInput questionIndex={index} question={question} />
            </div>
        </Group>
    )
}
