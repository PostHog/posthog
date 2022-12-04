import { ComponentMeta, ComponentStory } from '@storybook/react'
import { Query, QueryProps } from '~/queries/Query/Query'
import { useState } from 'react'
import { QueryEditor } from '~/queries/QueryEditor/QueryEditor'
import { examples } from './DataTable.examples'

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

export const NoColumns = BasicTemplate.bind({})
NoColumns.args = { query: examples['NoColumns'] }
