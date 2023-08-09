import { ComponentMeta, ComponentStory } from '@storybook/react'
import { Query } from '~/queries/Query/Query'
import { examples } from './InsightViz.examples'
import { mswDecorator } from '~/mocks/browser'

export default {
    title: 'Queries/InsightViz',
    component: Query,
    parameters: {
        options: { showPanel: false },
        viewMode: 'story',
        testOptions: {
            excludeNavigationFromSnapshot: true,
            snapshotBrowsers: ['chromium'],
            snapshotTargetSelector: 'insight-wrapper',
        },
    },
    argTypes: {
        query: { defaultValue: {} },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/insights/trend/': require('../../../scenes/insights/__mocks__/trendsLine.json'),
            },
        }),
    ],
} as ComponentMeta<typeof Query>

const QueryTemplate: ComponentStory<typeof Query> = (args) => <Query {...args} context={{ showQueryEditor: true }} />

export const AllDefaults = QueryTemplate.bind({})
AllDefaults.args = { query: examples['AllDefaults'] }

export const Minimalist = QueryTemplate.bind({})
Minimalist.args = { query: examples['Minimalist'] }
