import { DraggableSyntheticListeners } from '@dnd-kit/core'

import { SortableDragIcon } from 'lib/lemon-ui/icons'

interface SurveyDragHandleProps {
    listeners: DraggableSyntheticListeners | undefined
    hasMultipleQuestions: boolean
}

const DragHandle = ({ listeners }: { listeners: DraggableSyntheticListeners | undefined }): JSX.Element => (
    <span className="SurveyQuestionDragHandle" {...listeners} data-attr="survey-question-drag-handle">
        <SortableDragIcon />
    </span>
)

export function SurveyDragHandle({ listeners, hasMultipleQuestions }: SurveyDragHandleProps): JSX.Element | null {
    if (!hasMultipleQuestions) {
        return null
    }

    return <DragHandle listeners={listeners} />
}
