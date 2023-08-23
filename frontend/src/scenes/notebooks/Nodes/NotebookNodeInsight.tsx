import { InsightShortId } from '~/types'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType } from '~/types'
import { urls } from 'scenes/urls'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'
import { useValues } from 'kea'
import { notebookNodeLogic } from './notebookNodeLogic'
import { NotebookNodeViewProps } from '../Notebook/utils'

const Component = (props: NotebookNodeViewProps<NotebookNodeInsightAttributes>): JSX.Element | null => {
    const { expanded } = useValues(notebookNodeLogic)

    if (!expanded) {
        return null
    }
    return <Query query={{ kind: NodeKind.SavedInsightNode, shortId: props.node.attrs.id }} />
}

type NotebookNodeInsightAttributes = {
    id: InsightShortId
}

export const NotebookNodeInsight = createPostHogWidgetNode<NotebookNodeInsightAttributes>({
    nodeType: NotebookNodeType.Insight,
    title: 'Insight',
    Component,
    heightEstimate: '16rem',
    href: (attrs) => urls.insightView(attrs.id),
    resizeable: false,
    startExpanded: true,
    attributes: {
        id: {},
    },
    pasteOptions: {
        find: urls.insightView('(.+)' as InsightShortId),
        getAttributes: async (match) => {
            return { id: match[1] as InsightShortId }
        },
    },
})
