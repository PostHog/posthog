import { Handle, NodeProps, Position } from '@xyflow/react'

import { IconCheckCircle } from '@posthog/icons'

import { SurveyAppearancePreview } from '../../SurveyAppearancePreview'
import { END_NODE_SIMPLE_HEIGHT, END_NODE_SIMPLE_WIDTH } from '../constants'
import type { EndNode as EndNodeType } from '../types'
import { NodeBadge } from './NodeBadge'

export function EndNode({ data }: NodeProps<EndNodeType>): JSX.Element {
    const { survey } = data

    if (survey.appearance?.displayThankYouMessage) {
        return (
            <div className="end-node-with-preview relative">
                <NodeBadge>End</NodeBadge>

                <Handle type="target" position={Position.Left} className="!bg-border-bold !w-2 !h-2" />

                <div className="pointer-events-none">
                    <SurveyAppearancePreview survey={survey} previewPageIndex={survey.questions.length} />
                </div>
            </div>
        )
    }

    return (
        <div
            className="end-node-simple border-2 border-dashed border-border rounded-lg bg-bg-light flex items-center justify-center"
            style={{ width: END_NODE_SIMPLE_WIDTH, height: END_NODE_SIMPLE_HEIGHT }}
        >
            <Handle type="target" position={Position.Left} className="!bg-border" />

            <div className="flex items-center gap-1.5 text-muted text-xs">
                <IconCheckCircle className="text-success w-4 h-4" />
                <span>Survey ends</span>
            </div>
        </div>
    )
}
