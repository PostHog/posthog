import { ComponentMeta, ComponentStory } from '@storybook/react'
import { Query, QueryProps } from './Query'
import { EventsNode, LegacyQuery, Node, NodeKind, SavedInsightNode } from '~/queries/nodes'
import { InsightShortId, InsightType, PropertyOperator } from '~/types'
import { LemonTextArea } from 'lib/components/LemonTextArea/LemonTextArea'
import { useState } from 'react'

export default {
    title: 'Queries/Query',
    component: Query,
    parameters: { chromatic: { disableSnapshot: false } },
    argTypes: {
        query: { defaultValue: {} },
    },
} as ComponentMeta<typeof Query>

const BasicTemplate: ComponentStory<typeof Query> = (props: QueryProps) => {
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
            {JSONQuery ? <Query query={JSONQuery} /> : <div className="text-danger">Error parsing JSON: {error}</div>}
        </div>
    )
}

const legacyInsight: LegacyQuery = {
    kind: NodeKind.LegacyQuery,
    filters: { insight: InsightType.TRENDS },
}
export const LegacyInsight = BasicTemplate.bind({})
LegacyInsight.args = { query: legacyInsight }

const savedInsight: SavedInsightNode = {
    kind: NodeKind.SavedInsight,
    shortId: 'insight1234' as InsightShortId,
}
export const SavedInsight = BasicTemplate.bind({})
SavedInsight.args = { query: savedInsight }

const eventsTable: EventsNode = {
    kind: NodeKind.EventsNode,
    properties: [{ key: '$browser', value: 'Chrome', operator: PropertyOperator.Exact }],
}
export const EventsTable = BasicTemplate.bind({})
EventsTable.args = { query: eventsTable }
