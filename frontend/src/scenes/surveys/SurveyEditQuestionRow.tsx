import './EditSurvey.scss'

import { DraggableSyntheticListeners } from '@dnd-kit/core'
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { LemonButton } from '@posthog/lemon-ui'
import { IconDelete, SortableDragIcon } from 'lib/lemon-ui/icons'

import { Survey } from '~/types'

import { NewSurvey } from './constants'

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
                    icon={<IconDelete />}
                    status="primary-alt"
                    data-attr={`delete-survey-question-${index}`}
                    onClick={(e) => {
                        e.stopPropagation()
                        setSelectedQuestion(index <= 0 ? 0 : index - 1)
                        setSurveyValue(
                            'questions',
                            survey.questions.filter((_, i) => i !== index)
                        )
                    }}
                    tooltipPlacement="topRight"
                />
            )}
        </div>
    )
}
