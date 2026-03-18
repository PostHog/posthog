import { Handle, NodeProps, Position } from '@xyflow/react'

import { SurveyAppearancePreview } from '../../SurveyAppearancePreview'
import type { QuestionNode } from '../types'
import { NodeBadge } from './NodeBadge'

export function SurveyQuestionNode({ data }: NodeProps<QuestionNode>): JSX.Element {
    const { survey, questionIndex, sourceHandles } = data

    return (
        <div className="survey-question-node relative">
            <NodeBadge>{questionIndex === 0 ? 'Start' : `Q${questionIndex + 1}`}</NodeBadge>

            <Handle type="target" position={Position.Left} className="!bg-border-bold !w-2 !h-2" />

            <div className="pointer-events-none">
                <SurveyAppearancePreview
                    survey={{
                        ...survey,
                        appearance: {
                            ...survey.appearance,
                            hideCancelButton: true,
                            boxShadow: 'none',
                        },
                    }}
                    previewPageIndex={questionIndex}
                />
            </div>

            {sourceHandles.map((handle, index) => (
                <Handle
                    key={handle.id}
                    type="source"
                    position={Position.Right}
                    id={handle.id}
                    className="!bg-border-bold !w-2 !h-2"
                    style={{
                        top: `${((index + 1) / (sourceHandles.length + 1)) * 100}%`,
                    }}
                />
            ))}
        </div>
    )
}
