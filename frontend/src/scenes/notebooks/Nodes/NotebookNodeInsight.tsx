import { NodeViewProps } from '@tiptap/core'
import { InsightShortId } from '~/types'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType } from '~/types'
import { urls } from 'scenes/urls'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'

const HEIGHT = '16rem'

const Component = (props: NodeViewProps): JSX.Element => {
    return <Query query={{ kind: NodeKind.SavedInsightNode, shortId: props.node.attrs.id }} />
}

export const NotebookNodeInsight = createPostHogWidgetNode({
    nodeType: NotebookNodeType.Insight,
    title: 'Insight',
    Component,
    heightEstimate: HEIGHT,
    href: (attrs) => urls.insightView(attrs.id),
    resizeable: false,
    attributes: {
        id: {},
    },
    pasteOptions: {
        find: urls.insightView('(.+)' as InsightShortId),
        getAttributes: (match) => {
            return { id: match[1] }
        },
    },
})
