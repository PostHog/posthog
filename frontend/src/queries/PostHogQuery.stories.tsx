import { ComponentMeta, ComponentStory } from '@storybook/react'
import { PostHogQuery, PostHogQueryProps } from '~/queries/PostHogQuery'
import { EventsDataNode, LegacyQuery, Node, NodeType, SavedInsightNode } from '~/queries/nodes'
import { InsightShortId, InsightType, PropertyOperator } from '~/types'
import { LemonTextArea } from 'lib/components/LemonTextArea/LemonTextArea'
import { useState } from 'react'

export default {
    title: 'Components/PostHogQuery',
    component: PostHogQuery,
    parameters: { chromatic: { disableSnapshot: false } },
    argTypes: {
        query: { defaultValue: {} },
    },
} as ComponentMeta<typeof PostHogQuery>

const BasicTemplate: ComponentStory<typeof PostHogQuery> = (props: PostHogQueryProps) => {
    const [queryString, setQueryString] = useState(JSON.stringify(props.query, null, 2))
    let JSONQuery: Node | null = null
    let error = ''
    try {
        JSONQuery = JSON.parse(queryString)
    } catch (e: any) {
        error = e.message
    }

    return (
        <div className="p-2 space-y-2 flex flex-col border">
            <strong>Query:</strong>
            <LemonTextArea value={queryString} onChange={(v) => setQueryString(v)} />
            <strong>Response:</strong>
            {JSONQuery ? (
                <PostHogQuery query={JSONQuery} />
            ) : (
                <div className="text-danger">Error parsing JSON: {error}</div>
            )}
        </div>
    )
}

const legacyInsight: LegacyQuery = {
    nodeType: NodeType.LegacyQuery,
    filters: { insight: InsightType.TRENDS },
}
export const LegacyInsight = BasicTemplate.bind({})
LegacyInsight.args = { query: legacyInsight }

const savedInsight: SavedInsightNode = {
    nodeType: NodeType.SavedInsight,
    shortId: 'insight1234' as InsightShortId,
}
export const SavedInsight = BasicTemplate.bind({})
SavedInsight.args = { query: savedInsight }

const eventsTable: EventsDataNode = {
    nodeType: NodeType.EventsNode,
    properties: [{ key: '$browser', value: 'Chrome', operator: PropertyOperator.Exact }],
}
export const EventsTable = BasicTemplate.bind({})
EventsTable.args = { query: eventsTable }
