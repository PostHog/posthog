import { ReactNode } from 'react'

import { LemonTabs } from '@posthog/lemon-ui'

import type { TraceApi, TraceEvaluationResultApi, TraceNodeApi } from '../../../generated/api.schemas'
import { MessagesOpening, NodeDetailTab, NodeLoad, RawLoad } from '../types'
import { EvalResultList } from './EvalResultList'
import { NodeContentGate } from './NodeContentGate'
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
    load: NodeLoad
    trace: Pick<TraceApi, 'createdAt' | 'sessionId' | 'person'>
    /** Every result on the trace, null until they have loaded. */
    evaluationResults: TraceEvaluationResultApi[] | null
    evaluationResultsFailed: boolean
    stepLabels: ReadonlyMap<string, string>
    raw: RawLoad | undefined
    onViewInThread: (() => void) | null
    messagesOpening: MessagesOpening
    onMessagesOpeningChange: (opening: MessagesOpening) => void
    onSelectNode: (nodeId: string) => void
    actions?: ReactNode
    stepFeedback?: StepFeedbackChipsProps | null
    highlightQuery?: string | null
    matchStepCount?: number
}

export function NodeDetail(props: NodeDetailProps): JSX.Element {
    const highlightRef = useSearchHighlight(props.highlightQuery ?? null, props.matchStepCount)
    const detail = props.load.status === 'ready' ? props.load.node : null
    const propertyList = <NodePropertyList node={props.node} detail={detail} trace={props.trace} />
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
                                stepId={props.node.id}
                                load={props.load}
                                onViewInThread={props.onViewInThread}
                                opening={props.messagesOpening}
                                onOpeningChange={props.onMessagesOpeningChange}
                                highlightQuery={props.highlightQuery}
                            />
                        ),
                    },
                    {
                        key: 'details',
                        label: 'Details',
                        'data-attr': 'trace-view-detail-tab-details',
                        // The root's properties come from the trace, so they do not wait for its step read.
                        content:
                            props.node.kind === 'trace' ? (
                                propertyList
                            ) : (
                                <NodeContentGate load={props.load}>{() => propertyList}</NodeContentGate>
                            ),
                    },
                    {
                        key: 'evals',
                        label: 'Evals',
                        'data-attr': 'trace-view-detail-tab-evals',
                        content: (
                            <EvalResultList
                                results={props.evaluationResults}
                                failed={props.evaluationResultsFailed}
                                viewedNode={props.node}
                                stepLabels={props.stepLabels}
                                onSelectNode={props.onSelectNode}
                            />
                        ),
                    },
                    {
                        key: 'raw',
                        label: 'Raw',
                        'data-attr': 'trace-view-detail-tab-raw',
                        content: <NodeRawTab raw={props.raw} />,
                    },
                ]}
            />
        </div>
    )
}
