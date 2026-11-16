import { ReactNode } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import type { TraceNodeApi } from '../../../generated/api.schemas'
import { NodeKindGlyph } from './NodeKindGlyph'
import { NodeStatChips } from './NodeStatChips'
import { StepFeedbackChips, StepFeedbackChipsProps } from './StepFeedbackChips'

export interface NodeDetailHeaderProps {
    node: TraceNodeApi
    actions?: ReactNode
    stepFeedback?: StepFeedbackChipsProps | null
}

export function NodeDetailHeader({ node, actions, stepFeedback = null }: NodeDetailHeaderProps): JSX.Element {
    return (
        <header className="flex flex-col gap-1.5">
            <div className="flex items-center gap-2 min-w-0">
                <NodeKindGlyph kind={node.kind} size="medium" />
                <h3 className="m-0 truncate text-base font-semibold">{node.name}</h3>
                {actions ? <div className="ml-auto flex shrink-0 items-center gap-1">{actions}</div> : null}
            </div>
            <div className="flex flex-wrap items-center gap-1">
                <NodeStatChips stats={node.stats} />
                {node.model ? (
                    <LemonTag weight="normal" className="font-mono">
                        {node.model}
                    </LemonTag>
                ) : null}
                {node.hasError ? <LemonTag type="danger">Error</LemonTag> : null}
                {stepFeedback ? <StepFeedbackChips {...stepFeedback} /> : null}
            </div>
        </header>
    )
}
