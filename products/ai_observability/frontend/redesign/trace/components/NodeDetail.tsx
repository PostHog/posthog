import { ReactNode } from 'react'

import { LemonSkeleton, LemonTabs } from '@posthog/lemon-ui'

import type { TraceNodeApi } from '../../../generated/api.schemas'
import { EvalsState, NodeContent, NodeDetailTab, NodeProperties } from '../types'
import { ErrorCallout } from './ErrorCallout'
import { EvalResultList } from './EvalResultList'
import { NodeDetailHeader } from './NodeDetailHeader'
import { NodeMessagesTab } from './NodeMessagesTab'
import { NodePropertyList } from './NodePropertyList'
import { NodeRawTab } from './NodeRawTab'
import { StepFeedbackChipsProps } from './StepFeedbackChips'
import { useSearchHighlight } from './useSearchHighlight'

export interface NodeDetailProps {
    node: TraceNodeApi
    tab: NodeDetailTab
    onTabChange: (tab: NodeDetailTab) => void
    content: NodeContent
    error: string | null
    properties: NodeProperties
    evals: EvalsState
    raw: Record<string, unknown> | null
    onViewInThread: (() => void) | null
    onSelectNode: (nodeId: string) => void
    actions?: ReactNode
    stepFeedback?: StepFeedbackChipsProps | null
    highlightQuery?: string | null
    matchStepCount?: number
}

export function NodeDetail(props: NodeDetailProps): JSX.Element {
    const highlightRef = useSearchHighlight(props.highlightQuery ?? null, props.matchStepCount)
    return (
        <div className="flex min-w-0 flex-col gap-2" ref={highlightRef}>
            <NodeDetailHeader node={props.node} actions={props.actions} stepFeedback={props.stepFeedback} />
            <LemonTabs<NodeDetailTab>
                size="small"
                activeKey={props.tab}
                onChange={props.onTabChange}
                data-attr="trace-view-detail-tabs"
                tabs={[
                    {
                        key: 'messages',
                        label: 'Messages',
                        'data-attr': 'trace-view-detail-tab-messages',
                        content: (
                            <NodeMessagesTab
                                content={props.content}
                                error={props.error}
                                onViewInThread={props.onViewInThread}
                                highlightQuery={props.highlightQuery}
                            />
                        ),
                    },
                    {
                        key: 'details',
                        label: 'Details',
                        'data-attr': 'trace-view-detail-tab-details',
                        content: <NodePropertyList node={props.node} properties={props.properties} />,
                    },
                    {
                        key: 'evals',
                        label: 'Evals',
                        'data-attr': 'trace-view-detail-tab-evals',
                        content: <EvalResultList evals={props.evals} onSelectNode={props.onSelectNode} />,
                    },
                    {
                        key: 'raw',
                        label: 'Raw',
                        'data-attr': 'trace-view-detail-tab-raw',
                        content:
                            props.content.kind === 'loading' ? (
                                <LemonSkeleton repeat={3} className="h-16" />
                            ) : props.content.kind === 'error' ? (
                                <ErrorCallout message={props.content.message} />
                            ) : (
                                <NodeRawTab raw={props.raw} />
                            ),
                    },
                ]}
            />
        </div>
    )
}
