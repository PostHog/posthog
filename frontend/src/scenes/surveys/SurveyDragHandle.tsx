import { DraggableSyntheticListeners } from '@dnd-kit/core'
import { SortableDragIcon } from 'lib/lemon-ui/icons'

interface SurveyDragHandleProps {
    listeners: DraggableSyntheticListeners | undefined
    isDraftSurvey: boolean
    allQuestionsHaveIds: boolean
    hasMultipleQuestions: boolean
}

const DragHandle = ({ listeners }: { listeners: DraggableSyntheticListeners | undefined }): JSX.Element => (
    <span className="SurveyQuestionDragHandle" {...listeners} data-attr="survey-question-drag-handle">
        <SortableDragIcon />
    </span>
)

export function SurveyDragHandle({
    listeners,
    isDraftSurvey,
    hasMultipleQuestions,
    allQuestionsHaveIds,
}: SurveyDragHandleProps): JSX.Element | null {
    if (!hasMultipleQuestions) {
        return null
    }

    if (!allQuestionsHaveIds && !isDraftSurvey) {
        return null
    }

    return <DragHandle listeners={listeners} />
}
