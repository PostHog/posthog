import { InsightShortId, NotebookNodeType } from '~/types'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { urls } from 'scenes/urls'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'
import { useValues } from 'kea'
import { notebookNodeLogic } from './notebookNodeLogic'
import { NotebookNodeViewProps } from '../Notebook/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import api from 'lib/api'

const Component = (props: NotebookNodeViewProps<NotebookNodeInsightAttributes>): JSX.Element | null => {
    const { expanded } = useValues(notebookNodeLogic)

    if (!expanded) {
        return null
    }
    return <Query query={{ kind: NodeKind.SavedInsightNode, shortId: props.node.attrs.id, showHeader: false }} />
}

type NotebookNodeInsightAttributes = {
    id: InsightShortId
}

export const NotebookNodeInsight = createPostHogWidgetNode<NotebookNodeInsightAttributes>({
    nodeType: NotebookNodeType.Insight,
    title: async (attributes) => {
        const mountedInsightLogic = insightLogic.findMounted({ dashboardItemId: attributes.id })
        let title = mountedInsightLogic?.values.insightName || null

        if (title === null) {
            const response = await api.insights.loadInsight(attributes.id, true)
            if (response.results?.[0]) {
                title = response.results[0].name?.length
                    ? response.results[0].name
                    : response.results[0].derived_name || null
            }
        }

        return title ? `Insight: ${title}` : 'Insight'
    },
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
