import { LemonButton } from "@posthog/lemon-ui"
import { IconDelete, SortableDragIcon } from "lib/lemon-ui/icons"
import { CSS } from '@dnd-kit/utilities'
import { DraggableSyntheticListeners } from "@dnd-kit/core"
import { useSortable } from "@dnd-kit/sortable"


export function SurveyEditQuestionRow(): JSX.Element {
 return (<></>)
}

export function SurveyEditQuestionHeader({ index, survey, setSelectedQuestion, setSurveyValue }): JSX.Element {
    const DragHandle = (props: DraggableSyntheticListeners | undefined): JSX.Element => (
        <span className="SurveyQuestionDragHandle" {...props}>
            <SortableDragIcon />
        </span>
    )
    const { setNodeRef, attributes, transform, transition, listeners, isDragging } = useSortable({ id: index })
    const questionsStartElements = [survey.questions.length > 1 ? <DragHandle {...listeners} /> : null].filter(Boolean)
    
    return (
        <div 
        className="flex flex-row w-full items-center justify-between" 
        ref={setNodeRef} {...attributes}             
        style={{
            position: 'relative',
            zIndex: isDragging ? 1 : undefined,
            transform: CSS.Translate.toString(transform),
            transition,
        }}>
        {questionsStartElements.length ? (
            <div className="SurveyQuestionHeader__start">{questionsStartElements}</div>
        ) : null}

        <b>
            Question {index + 1}. {survey.questions[index].question}
        </b>
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
                        survey.questions.filter(
                            (_, i) => i !== index
                        )
                    )
                }}
                tooltipPlacement="topRight"
            />
        )}
    </div>
    )
}