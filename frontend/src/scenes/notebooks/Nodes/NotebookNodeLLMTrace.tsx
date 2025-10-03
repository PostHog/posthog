import { useValues } from 'kea'

import { LLMAnalyticsTraces } from 'products/llm_analytics/frontend/LLMAnalyticsTracesScene'

import { NotebookNodeProps, NotebookNodeType } from '../types'
import { createPostHogWidgetNode } from './NodeWrapper'
import { notebookNodeLogic } from './notebookNodeLogic'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeLLMTraceAttributes>): JSX.Element | null => {
    const { expanded } = useValues(notebookNodeLogic)
    const { personId } = attributes

    if (!expanded) {
        return null
    }

    return <LLMAnalyticsTraces personId={personId} />
}

type NotebookNodeLLMTraceAttributes = {
    personId?: string
}

export const NotebookNodeLLMTrace = createPostHogWidgetNode<NotebookNodeLLMTraceAttributes>({
    nodeType: NotebookNodeType.LLMTrace,
    titlePlaceholder: 'Traces',
    Component,
    resizeable: false,
    expandable: true,
    startExpanded: true,
    attributes: {
        personId: {},
    },
})
