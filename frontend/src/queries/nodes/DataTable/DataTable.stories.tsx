import { ComponentMeta, ComponentStory } from '@storybook/react'
import { Query, QueryProps } from '~/queries/Query/Query'
import { useState } from 'react'
import { QueryEditor } from '~/queries/QueryEditor/QueryEditor'
import { examples } from './DataTable.examples'
import { mswDecorator } from '~/mocks/browser'
import events from './__mocks__/EventsNode.json'

export default {
    title: 'Queries/DataTable',
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
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:projectId/events': events,
            },
        }),
    ],
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

export const AllDefaults = BasicTemplate.bind({})
AllDefaults.args = { query: examples['AllDefaults'] }

export const Minimalist = BasicTemplate.bind({})
Minimalist.args = { query: examples['Minimalist'] }

export const ManyColumns = BasicTemplate.bind({})
ManyColumns.args = { query: examples['ManyColumns'] }

export const ShowFilters = BasicTemplate.bind({})
ShowFilters.args = { query: examples['ShowFilters'] }

export const ShowTools = BasicTemplate.bind({})
ShowTools.args = { query: examples['ShowTools'] }

export const ShowAllTheThings = BasicTemplate.bind({})
ShowAllTheThings.args = { query: examples['ShowAllTheThings'] }
