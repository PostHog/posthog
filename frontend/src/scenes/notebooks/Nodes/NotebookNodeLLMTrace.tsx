import { useValues } from 'kea'

import { LLMAnalyticsTraces } from 'products/llm_analytics/frontend/LLMAnalyticsTracesScene'

import { NotebookNodeType } from '../types'
import { createPostHogWidgetNode } from './NodeWrapper'
import { notebookNodeLogic } from './notebookNodeLogic'

const Component = (): JSX.Element | null => {
    const { expanded } = useValues(notebookNodeLogic)

    if (!expanded) {
        return null
    }

    return <LLMAnalyticsTraces />
}

type NotebookNodeLLMTraceAttributes = {}

export const NotebookNodeLLMTrace = createPostHogWidgetNode<NotebookNodeLLMTraceAttributes>({
    nodeType: NotebookNodeType.LLMTrace,
    titlePlaceholder: 'Traces',
    Component,
    resizeable: false,
    expandable: true,
    startExpanded: true,
    attributes: {},
})
