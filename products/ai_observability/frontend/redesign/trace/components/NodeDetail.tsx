import { LemonTabs } from '@posthog/lemon-ui'

import { EvalsState, NodeContent, NodeDetailTab, NodeProperties, TraceTreeNode } from '../types'
import { EvalResultList } from './EvalResultList'
import { NodeDetailHeader } from './NodeDetailHeader'
import { NodeMessagesTab } from './NodeMessagesTab'
import { NodePropertyList } from './NodePropertyList'
import { NodeRawTab } from './NodeRawTab'

export interface NodeDetailProps {
    node: TraceTreeNode
    tab: NodeDetailTab
    onTabChange: (tab: NodeDetailTab) => void
    content: NodeContent
    error: string | null
    properties: NodeProperties
    evals: EvalsState
    raw: Record<string, unknown>
    onViewInThread: (() => void) | null
}

export function NodeDetail(props: NodeDetailProps): JSX.Element {
    return (
        <div className="flex min-w-0 flex-col gap-2">
            <NodeDetailHeader node={props.node} />
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
                            />
                        ),
                    },
                    {
                        key: 'details',
                        label: 'Details',
                        'data-attr': 'trace-view-detail-tab-details',
                        content: <NodePropertyList properties={props.properties} />,
                    },
                    {
                        key: 'evals',
                        label: 'Evals',
                        'data-attr': 'trace-view-detail-tab-evals',
                        content: <EvalResultList evals={props.evals} />,
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
