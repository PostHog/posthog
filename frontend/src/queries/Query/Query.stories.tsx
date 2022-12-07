import { ComponentMeta, ComponentStory } from '@storybook/react'
import { Query, QueryProps } from './Query'
import { useState } from 'react'
import { QueryEditor } from '~/queries/QueryEditor/QueryEditor'
import { examples } from '../examples'

export default {
    title: 'Queries/Query',
    component: Query,
    parameters: {
        chromatic: { disableSnapshot: false },
        layout: 'fullscreen',
        options: { showPanel: false },
        viewMode: 'story',
    },
    argTypes: {
        query: { defaultValue: {} },
    },
} as ComponentMeta<typeof Query>

const BasicTemplate: ComponentStory<typeof Query> = (props: QueryProps) => {
    const [queryString, setQueryString] = useState(JSON.stringify(props.query))

    return (
        <>
            <QueryEditor query={queryString} setQuery={setQueryString} />
            <div className="p-4">
                <Query key={queryString} query={queryString} />
            </div>
        </>
    )
}

export const Events = BasicTemplate.bind({})
Events.args = { query: examples['Events'] }

export const EventsTable = BasicTemplate.bind({})
EventsTable.args = { query: examples['EventsTable'] }

export const LegacyTrendsQuery = BasicTemplate.bind({})
LegacyTrendsQuery.args = { query: examples['LegacyTrendsQuery'] }

export const InsightTrendsQuery = BasicTemplate.bind({})
InsightTrendsQuery.args = { query: examples['InsightTrendsQuery'] }
