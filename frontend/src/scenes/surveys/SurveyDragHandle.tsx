import { DraggableSyntheticListeners } from '@dnd-kit/core'
import { SortableDragIcon } from 'lib/lemon-ui/icons'

interface SurveyDragHandleProps {
    listeners: DraggableSyntheticListeners | undefined
    isDraftSurvey: boolean
    hasMultipleQuestions: boolean
}

const DragHandle = ({ listeners }: { listeners: DraggableSyntheticListeners | undefined }): JSX.Element => (
    <span className="SurveyQuestionDragHandle" {...listeners} data-testid="survey-question-drag-handle">
        <SortableDragIcon />
    </span>
)

export function SurveyDragHandle({
    listeners,
    isDraftSurvey,
    hasMultipleQuestions,
}: SurveyDragHandleProps): JSX.Element | null {
    if (!isDraftSurvey || !hasMultipleQuestions) {
        return null
    }

    return <DragHandle listeners={listeners} />
}
