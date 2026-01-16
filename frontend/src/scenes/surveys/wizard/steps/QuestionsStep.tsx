import { DndContext, DragEndEvent } from '@dnd-kit/core'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useActions, useValues } from 'kea'

import { IconRevert, IconTrash } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { EditableField } from 'lib/components/EditableField/EditableField'
import { SortableDragIcon } from 'lib/lemon-ui/icons'

import { SurveyQuestion } from '~/types'

import { SurveyQuestionLabel } from '../../constants'
import { surveyLogic } from '../../surveyLogic'
import { surveyWizardLogic } from '../surveyWizardLogic'

interface SortableQuestionCardProps {
    question: SurveyQuestion
    index: number
    canDelete: boolean
    canReorder: boolean
    onUpdate: (index: number, updates: Partial<SurveyQuestion>) => void
    onDelete: (index: number) => void
}

function SortableQuestionCard({
    question,
    index,
    canDelete,
    canReorder,
    onUpdate,
    onDelete,
}: SortableQuestionCardProps): JSX.Element {
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
        id: index.toString(),
    })

    const style = {
        transform: CSS.Transform.toString(transform),
        transition,
        zIndex: isDragging ? 1 : undefined,
        opacity: isDragging ? 0.9 : 1,
    }

    return (
        <div
            ref={setNodeRef}
            style={style}
            {...attributes}
            className="group border border-border rounded-lg p-4 bg-bg-light hover:border-border-bold transition-colors"
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
                    />
                    <div className="flex items-center gap-2">
                        <LemonTag type="muted" size="small">
                            {SurveyQuestionLabel[question.type]}
                        </LemonTag>
                        {question.optional && (
                            <LemonTag type="highlight" size="small">
                                Optional
                            </LemonTag>
                        )}
                    </div>
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

    const handleDragEnd = (event: DragEndEvent): void => {
        const { active, over } = event
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

            <DndContext onDragEnd={handleDragEnd}>
                <SortableContext items={sortedItemIds} strategy={verticalListSortingStrategy} disabled={!canReorder}>
                    <div className="space-y-3">
                        {questions.map((question: SurveyQuestion, index: number) => (
                            <SortableQuestionCard
                                key={index}
                                question={question}
                                index={index}
                                canDelete={canDelete}
                                canReorder={canReorder}
                                onUpdate={updateQuestion}
                                onDelete={deleteQuestion}
                            />
                        ))}
                    </div>
                </SortableContext>
            </DndContext>
        </div>
    )
}
