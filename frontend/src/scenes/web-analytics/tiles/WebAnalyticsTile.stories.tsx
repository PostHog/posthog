import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useActions } from 'kea'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { mswDecorator } from '~/mocks/browser'
import { Query } from '~/queries/Query/Query'
import { examples } from '~/queries/examples'
import { WebAnalyticsOrderByFields } from '~/queries/schema/schema-general'

import { webAnalyticsLogic } from '../webAnalyticsLogic'
import { webAnalyticsDataTableQueryContext } from './WebAnalyticsTile'
import browserMock from './__mocks__/Browser.json'
import pathMock from './__mocks__/Path.json'
import referringDomainMock from './__mocks__/ReferringDomain.json'
import retentionMock from './__mocks__/Retention.json'
import worldMapMock from './__mocks__/WorldMap.json'

type Story = StoryObj<typeof Query>
const meta: Meta<typeof Query> = {
    title: 'Web Analytics/Tiles',
    component: Query,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/': (req) => {
                    if ((req.body as any).query.kind === 'WebStatsTableQuery') {
                        if ((req.body as any).query.breakdownBy === 'InitialReferringDomain') {
                            return [200, referringDomainMock]
                        } else if ((req.body as any).query.breakdownBy === 'Page') {
                            return [200, pathMock]
                        } else if ((req.body as any).query.breakdownBy === 'Browser') {
                            return [200, browserMock]
                        }
                    } else if ((req.body as any).query.kind === 'TrendsQuery') {
                        if ((req.body as any).query.trendsFilter?.display === 'WorldMap') {
                            return [200, worldMapMock]
                        }
                    } else if ((req.body as any).query.kind === 'RetentionQuery') {
                        return [200, retentionMock]
                    }
                },
            },
        }),
    ],
}
export default meta

const Template: StoryFn<typeof Query> = (args) => {
    const { setTablesOrderBy } = useActions(webAnalyticsLogic)
    useDelayedOnMountEffect(() => setTablesOrderBy('Views' as WebAnalyticsOrderByFields, 'DESC'))

    return <Query {...args} context={{ ...webAnalyticsDataTableQueryContext }} readOnly />
}

export const WorldMap: Story = Template.bind({})
WorldMap.args = { query: examples['WebAnalyticsWorldMap'] }

export const ReferrerDomain: Story = Template.bind({})
ReferrerDomain.args = { query: examples['WebAnalyticsReferrerDomain'] }

export const Path: Story = Template.bind({})
Path.args = { query: examples['WebAnalyticsPath'] }

export const Retention: Story = Template.bind({})
Retention.args = { query: examples['WebAnalyticsRetention'] }

export const Browser: Story = Template.bind({})
Browser.args = { query: examples['WebAnalyticsBrowser'] }
