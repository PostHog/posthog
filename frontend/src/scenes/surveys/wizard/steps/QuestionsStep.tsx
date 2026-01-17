import { DndContext, DragEndEvent, DragOverlay, DragStartEvent } from '@dnd-kit/core'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useActions, useValues } from 'kea'
import { AnimatePresence, motion } from 'motion/react'
import { useState } from 'react'
import { createPortal } from 'react-dom'

import { IconEmoji, IconPlusSmall, IconRevert, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonSwitch, LemonTag } from '@posthog/lemon-ui'

import { EditableField } from 'lib/components/EditableField/EditableField'
import { SortableDragIcon } from 'lib/lemon-ui/icons'

import {
    LinkSurveyQuestion,
    MultipleSurveyQuestion,
    RatingSurveyQuestion,
    SurveyAppearance,
    SurveyQuestion,
    SurveyQuestionType,
} from '~/types'

import { SURVEY_RATING_SCALE, defaultSurveyAppearance, defaultSurveyFieldValues } from '../../constants'
import { surveyLogic } from '../../surveyLogic'
import { AddQuestionButton } from '../AddQuestionButton'
import { QuestionTypeChip } from '../QuestionTypeChip'
import { surveyWizardLogic } from '../surveyWizardLogic'

const MAX_CHOICES = 10

interface QuestionOptionsProps {
    question: SurveyQuestion
    onUpdate: (updates: Partial<SurveyQuestion>) => void
}

function QuestionOptions({ question, onUpdate }: QuestionOptionsProps): JSX.Element | null {
    // Rating question options
    if (question.type === SurveyQuestionType.Rating) {
        const ratingQuestion = question as RatingSurveyQuestion
        const isEmoji = ratingQuestion.display === 'emoji'

        // Scale options depend on display type
        const numberScales = [
            { value: 10, label: '0-10', sublabel: 'NPS' },
            { value: 5, label: '1-5', sublabel: null },
            { value: 7, label: '1-7', sublabel: 'CSAT' },
        ]
        const emojiScales = [
            { value: 3, label: '3', sublabel: null },
            { value: 5, label: '5', sublabel: null },
        ]
        const scaleOptions = isEmoji ? emojiScales : numberScales

        return (
            <div className="space-y-3 pt-3 border-t border-border mt-3">
                <div className="flex items-start gap-6">
                    {/* Display type toggle */}
                    <div className="space-y-1.5">
                        <span className="text-xs text-secondary">Display</span>
                        <div className="flex rounded-md border border-border overflow-hidden">
                            <button
                                type="button"
                                onClick={() =>
                                    onUpdate({
                                        display: 'emoji',
                                        scale: SURVEY_RATING_SCALE.LIKERT_5_POINT,
                                    } as Partial<RatingSurveyQuestion>)
                                }
                                className={`px-3 py-2 transition-colors ${
                                    isEmoji ? 'bg-fill-highlight-100' : 'hover:bg-fill-highlight-50'
                                }`}
                            >
                                <IconEmoji className="text-lg" />
                            </button>
                            <button
                                type="button"
                                onClick={() =>
                                    onUpdate({
                                        display: 'number',
                                        scale: SURVEY_RATING_SCALE.LIKERT_5_POINT,
                                    } as Partial<RatingSurveyQuestion>)
                                }
                                className={`px-3 py-2 text-sm font-medium border-l border-border transition-colors ${
                                    !isEmoji ? 'bg-fill-highlight-100' : 'hover:bg-fill-highlight-50'
                                }`}
                            >
                                1-5
                            </button>
                        </div>
                    </div>

                    {/* Scale toggle */}
                    <div className="space-y-1.5">
                        <span className="text-xs text-secondary">Scale</span>
                        <div className="flex rounded-md border border-border overflow-hidden">
                            {scaleOptions.map((option, idx) => (
                                <button
                                    key={option.value}
                                    type="button"
                                    onClick={() => onUpdate({ scale: option.value } as Partial<RatingSurveyQuestion>)}
                                    className={`px-3 py-1.5 text-center transition-colors ${
                                        idx > 0 ? 'border-l border-border' : ''
                                    } ${
                                        ratingQuestion.scale === option.value
                                            ? 'bg-fill-highlight-100'
                                            : 'hover:bg-fill-highlight-50'
                                    }`}
                                >
                                    <div className="text-sm font-medium">{option.label}</div>
                                    {option.sublabel && (
                                        <div className="text-[10px] text-secondary uppercase">{option.sublabel}</div>
                                    )}
                                </button>
                            ))}
                        </div>
                    </div>
                </div>

                {/* Labels */}
                <div className="flex items-center gap-3">
                    <div className="flex-1">
                        <span className="text-xs text-secondary block mb-1">Lower label</span>
                        <LemonInput
                            size="xsmall"
                            value={ratingQuestion.lowerBoundLabel || ''}
                            placeholder="e.g. Unlikely"
                            onChange={(val) => onUpdate({ lowerBoundLabel: val } as Partial<RatingSurveyQuestion>)}
                            fullWidth
                        />
                    </div>
                    <div className="flex-1">
                        <span className="text-xs text-secondary block mb-1">Upper label</span>
                        <LemonInput
                            size="xsmall"
                            value={ratingQuestion.upperBoundLabel || ''}
                            placeholder="e.g. Very likely"
                            onChange={(val) => onUpdate({ upperBoundLabel: val } as Partial<RatingSurveyQuestion>)}
                            fullWidth
                        />
                    </div>
                </div>
            </div>
        )
    }

    // Single/Multiple choice question options
    if (question.type === SurveyQuestionType.SingleChoice || question.type === SurveyQuestionType.MultipleChoice) {
        const choiceQuestion = question as MultipleSurveyQuestion
        const choices = choiceQuestion.choices || []
        const hasOpenChoice = choiceQuestion.hasOpenChoice

        const updateChoice = (choiceIndex: number, value: string): void => {
            const newChoices = [...choices]
            newChoices[choiceIndex] = value
            onUpdate({ choices: newChoices } as Partial<MultipleSurveyQuestion>)
        }

        const removeChoice = (choiceIndex: number): void => {
            const newChoices = choices.filter((_, i) => i !== choiceIndex)
            const isRemovingOpenChoice = hasOpenChoice && choiceIndex === choices.length - 1
            onUpdate({
                choices: newChoices,
                ...(isRemovingOpenChoice ? { hasOpenChoice: false } : {}),
            } as Partial<MultipleSurveyQuestion>)
        }

        const addChoice = (): void => {
            if (hasOpenChoice) {
                // Insert before the open-ended choice
                const newChoices = [...choices.slice(0, -1), '', choices[choices.length - 1]]
                onUpdate({ choices: newChoices } as Partial<MultipleSurveyQuestion>)
            } else {
                onUpdate({ choices: [...choices, ''] } as Partial<MultipleSurveyQuestion>)
            }
        }

        const addOpenEndedChoice = (): void => {
            onUpdate({
                choices: [...choices, 'Other'],
                hasOpenChoice: true,
            } as Partial<MultipleSurveyQuestion>)
        }

        return (
            <div className="space-y-2 pt-2 border-t border-border mt-3">
                <span className="text-xs text-secondary">Choices:</span>
                <div className="space-y-1.5">
                    {choices.map((choice, choiceIndex) => {
                        const isOpenChoice = hasOpenChoice && choiceIndex === choices.length - 1
                        return (
                            <div key={choiceIndex} className="flex items-center gap-1.5">
                                <LemonInput
                                    size="xsmall"
                                    value={choice}
                                    placeholder={isOpenChoice ? 'Other (open-ended)' : `Choice ${choiceIndex + 1}`}
                                    onChange={(val) => updateChoice(choiceIndex, val)}
                                    className="flex-1"
                                    suffix={
                                        isOpenChoice ? (
                                            <LemonTag type="highlight" size="small">
                                                open
                                            </LemonTag>
                                        ) : null
                                    }
                                />
                                <LemonButton
                                    icon={<IconTrash />}
                                    size="xsmall"
                                    type="tertiary"
                                    onClick={() => removeChoice(choiceIndex)}
                                    tooltip="Remove choice"
                                />
                            </div>
                        )
                    })}
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                    {choices.length < MAX_CHOICES && (
                        <LemonButton icon={<IconPlusSmall />} size="xsmall" type="secondary" onClick={addChoice}>
                            Add choice
                        </LemonButton>
                    )}
                    {!hasOpenChoice && choices.length < MAX_CHOICES && (
                        <LemonButton
                            icon={<IconPlusSmall />}
                            size="xsmall"
                            type="secondary"
                            onClick={addOpenEndedChoice}
                        >
                            Add "Other"
                        </LemonButton>
                    )}
                    <LemonCheckbox
                        label="Shuffle"
                        checked={!!choiceQuestion.shuffleOptions}
                        onChange={(checked) => onUpdate({ shuffleOptions: checked } as Partial<MultipleSurveyQuestion>)}
                        size="small"
                    />
                </div>
            </div>
        )
    }

    // Link question options
    if (question.type === SurveyQuestionType.Link) {
        const linkQuestion = question as LinkSurveyQuestion
        const linkValue = linkQuestion.link || ''
        const isValidLink = !linkValue || linkValue.startsWith('https://') || linkValue.startsWith('mailto:')

        return (
            <div className="space-y-3 pt-3 border-t border-border mt-3">
                <div className="flex items-center gap-3">
                    <div className="flex-1">
                        <span className="text-xs text-secondary block mb-1">Button text</span>
                        <LemonInput
                            size="xsmall"
                            value={linkQuestion.buttonText || ''}
                            placeholder="Learn more"
                            onChange={(val) => onUpdate({ buttonText: val })}
                            fullWidth
                        />
                    </div>
                    <div className="flex-1">
                        <span className="text-xs text-secondary block mb-1">Link URL</span>
                        <LemonInput
                            size="xsmall"
                            value={linkValue}
                            placeholder="https://example.com"
                            onChange={(val) => onUpdate({ link: val })}
                            fullWidth
                            status={isValidLink ? 'default' : 'danger'}
                        />
                    </div>
                </div>
                {!isValidLink ? (
                    <p className="text-xs text-danger">Link must start with https:// or mailto:</p>
                ) : (
                    <p className="text-xs text-secondary">
                        Only https:// or mailto: links are supported. Leave empty for announcement-only.
                    </p>
                )}
            </div>
        )
    }

    // Open text questions have no additional options
    return null
}

interface ConfirmationScreenEditorProps {
    appearance: SurveyAppearance
    onUpdate: (updates: Partial<SurveyAppearance>) => void
}

function ConfirmationScreenEditor({ appearance, onUpdate }: ConfirmationScreenEditorProps): JSX.Element {
    const isEnabled = appearance.displayThankYouMessage ?? true

    return (
        <div className="border border-border rounded-lg bg-bg-light overflow-hidden">
            {/* Always visible header with toggle */}
            <div className="flex items-center justify-between gap-2 px-3 py-2.5">
                <span className="text-sm font-medium">Confirmation screen</span>
                <LemonSwitch
                    checked={isEnabled}
                    onChange={(checked) => onUpdate({ displayThankYouMessage: checked })}
                />
            </div>

            {/* Animated expandable content */}
            <AnimatePresence initial={false}>
                {isEnabled && (
                    <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.2, ease: [0.25, 1, 0.5, 1] }}
                    >
                        <div className="px-3 pb-3 space-y-2 border-t border-border pt-2.5">
                            <EditableField
                                name="confirmation-header"
                                value={appearance.thankYouMessageHeader || ''}
                                onSave={(text) => onUpdate({ thankYouMessageHeader: text })}
                                placeholder="Thank you for your feedback!"
                                className="font-medium text-sm"
                                saveOnBlur
                                clickToEdit
                                compactIcon
                                showEditIconOnHover
                            />
                            <EditableField
                                name="confirmation-description"
                                value={appearance.thankYouMessageDescription || ''}
                                onSave={(text) => onUpdate({ thankYouMessageDescription: text })}
                                placeholder="Add a description (optional)"
                                className="text-secondary text-xs"
                                saveOnBlur
                                clickToEdit
                                compactIcon
                                showEditIconOnHover
                            />
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    )
}

interface QuestionCardProps {
    question: SurveyQuestion
    index: number
    canReorder: boolean
}

function QuestionCardOverlay({ question, index, canReorder }: QuestionCardProps): JSX.Element {
    return (
        <div className="border border-border rounded-lg p-4 bg-bg-light shadow-lg cursor-grabbing">
            <div className="flex items-start gap-2">
                {canReorder && (
                    <span className="text-secondary mt-0.5">
                        <SortableDragIcon />
                    </span>
                )}
                <span className="font-medium text-base shrink-0 w-6">{index + 1}.</span>
                <div className="flex-1 min-w-0 space-y-2">
                    <div className="font-medium text-base">{question.question || 'Enter your question'}</div>
                    {question.description && <div className="text-secondary text-sm">{question.description}</div>}
                    <QuestionTypeChip type={question.type} onChange={() => {}} />
                </div>
            </div>
        </div>
    )
}

interface SortableQuestionCardProps {
    question: SurveyQuestion
    index: number
    canDelete: boolean
    canReorder: boolean
    onUpdate: (index: number, updates: Partial<SurveyQuestion>) => void
    onChangeType: (index: number, newType: SurveyQuestionType) => void
    onDelete: (index: number) => void
}

function SortableQuestionCard({
    question,
    index,
    canDelete,
    canReorder,
    onUpdate,
    onChangeType,
    onDelete,
}: SortableQuestionCardProps): JSX.Element {
    const { attributes, listeners, setNodeRef, transform, isDragging } = useSortable({
        id: index.toString(),
        animateLayoutChanges: () => false,
    })

    const style = {
        transform: CSS.Translate.toString(transform),
    }

    return (
        <div
            ref={setNodeRef}
            style={style}
            {...attributes}
            className={`group border border-border rounded-lg p-4 bg-bg-light hover:border-border-bold transition-colors ${
                isDragging ? 'opacity-50' : ''
            }`}
        >
            <div className="flex items-start gap-2">
                {/* Drag handle */}
                {canReorder && (
                    <span
                        className="cursor-grab active:cursor-grabbing text-secondary hover:text-primary transition-colors mt-0.5"
                        {...listeners}
                    >
                        <SortableDragIcon />
                    </span>
                )}

                <span className="font-medium text-base shrink-0 w-6">{index + 1}.</span>
                <div className="flex-1 min-w-0 space-y-2">
                    <EditableField
                        name={`question-${index}`}
                        value={question.question}
                        onSave={(text) => onUpdate(index, { question: text })}
                        placeholder="Enter your question"
                        className="font-medium text-base"
                        saveOnBlur
                        clickToEdit
                        compactIcon
                        showEditIconOnHover
                    />
                    <EditableField
                        name={`description-${index}`}
                        value={question.description || ''}
                        onSave={(text) => onUpdate(index, { description: text })}
                        placeholder="Add description (optional)"
                        className="text-secondary text-sm"
                        saveOnBlur
                        clickToEdit
                        compactIcon
                        showEditIconOnHover
                    />
                    <div className="flex items-center gap-2">
                        <QuestionTypeChip type={question.type} onChange={(newType) => onChangeType(index, newType)} />
                        {question.optional && (
                            <LemonTag type="highlight" size="small">
                                Optional
                            </LemonTag>
                        )}
                    </div>

                    <QuestionOptions question={question} onUpdate={(updates) => onUpdate(index, updates)} />
                </div>
                {canDelete && (
                    <LemonButton
                        icon={<IconTrash />}
                        size="small"
                        type="tertiary"
                        tooltip="Remove question"
                        className="opacity-0 group-hover:opacity-100 transition-opacity"
                        onClick={() => onDelete(index)}
                    />
                )}
            </div>
        </div>
    )
}

export function QuestionsStep(): JSX.Element {
    const { survey } = useValues(surveyLogic)
    const { setSurveyValue } = useActions(surveyLogic)
    const { selectedTemplate } = useValues(surveyWizardLogic)
    const { restoreDefaultQuestions } = useActions(surveyWizardLogic)

    const [activeId, setActiveId] = useState<string | null>(null)

    const questions = survey.questions as SurveyQuestion[]
    const sortedItemIds = questions.map((_, index) => index.toString())

    const updateQuestion = (index: number, updates: Partial<SurveyQuestion>): void => {
        const newQuestions = [...questions]
        newQuestions[index] = { ...newQuestions[index], ...updates } as SurveyQuestion
        setSurveyValue('questions', newQuestions)
    }

    const deleteQuestion = (index: number): void => {
        const newQuestions = questions.filter((_, i) => i !== index)
        setSurveyValue('questions', newQuestions)
    }

    const addQuestion = (type: SurveyQuestionType): void => {
        const defaultQuestion = defaultSurveyFieldValues[type].questions[0]
        setSurveyValue('questions', [...questions, defaultQuestion])
    }

    const changeQuestionType = (index: number, newType: SurveyQuestionType): void => {
        const currentQuestion = questions[index]
        if (currentQuestion.type === newType) {
            return
        }

        const defaultQuestion = defaultSurveyFieldValues[newType].questions[0]
        const newQuestions = [...questions]
        newQuestions[index] = {
            ...defaultQuestion,
            question: currentQuestion.question,
            description: currentQuestion.description,
            descriptionContentType: currentQuestion.descriptionContentType,
            optional: currentQuestion.optional,
        } as SurveyQuestion
        setSurveyValue('questions', newQuestions)
    }

    const handleDragStart = (event: DragStartEvent): void => {
        setActiveId(event.active.id.toString())
    }

    const handleDragEnd = (event: DragEndEvent): void => {
        const { active, over } = event
        setActiveId(null)

        if (over && active.id !== over.id) {
            const oldIndex = sortedItemIds.indexOf(active.id.toString())
            const newIndex = sortedItemIds.indexOf(over.id.toString())

            const newQuestions = [...questions]
            const [removed] = newQuestions.splice(oldIndex, 1)
            newQuestions.splice(newIndex, 0, removed)
            setSurveyValue('questions', newQuestions)
        }
    }

    const canDelete = questions.length > 1
    const canReorder = questions.length > 1
    const hasChanges = selectedTemplate && JSON.stringify(questions) !== JSON.stringify(selectedTemplate.questions)

    const activeIndex = activeId ? parseInt(activeId, 10) : null
    const activeQuestion = activeIndex !== null ? questions[activeIndex] : null

    return (
        <div className="space-y-6">
            <div className="flex items-start justify-between gap-4">
                <div className="space-y-1">
                    <h2 className="text-xl font-semibold">Your survey questions</h2>
                    <p className="text-secondary text-sm">Click any question to edit it</p>
                </div>
                {hasChanges && (
                    <LemonButton type="tertiary" size="small" icon={<IconRevert />} onClick={restoreDefaultQuestions}>
                        Restore defaults
                    </LemonButton>
                )}
            </div>

            <DndContext onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
                <SortableContext items={sortedItemIds} strategy={verticalListSortingStrategy} disabled={!canReorder}>
                    <div className="space-y-3">
                        {questions.map((question: SurveyQuestion, index: number) => (
                            <SortableQuestionCard
                                key={index.toString()}
                                question={question}
                                index={index}
                                canDelete={canDelete}
                                canReorder={canReorder}
                                onUpdate={updateQuestion}
                                onChangeType={changeQuestionType}
                                onDelete={deleteQuestion}
                            />
                        ))}
                    </div>
                </SortableContext>

                {createPortal(
                    <DragOverlay>
                        {activeQuestion && activeIndex !== null ? (
                            <QuestionCardOverlay
                                question={activeQuestion}
                                index={activeIndex}
                                canReorder={canReorder}
                            />
                        ) : null}
                    </DragOverlay>,
                    document.body
                )}
            </DndContext>

            <AddQuestionButton onAdd={addQuestion} />

            {/* Confirmation screen editor */}
            <ConfirmationScreenEditor
                appearance={{ ...defaultSurveyAppearance, ...survey.appearance }}
                onUpdate={(updates) => setSurveyValue('appearance', { ...survey.appearance, ...updates })}
            />
        </div>
    )
}
