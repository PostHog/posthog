import type { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { mswDecorator } from '~/mocks/browser'
import { examples } from '~/queries/examples'
import { Query, QueryProps } from '~/queries/Query/Query'
import { Node, WebAnalyticsOrderByFields } from '~/queries/schema/schema-general'

import { webAnalyticsLogic } from '../webAnalyticsLogic'
import browserMock from './__mocks__/Browser.json'
import pathMock from './__mocks__/Path.json'
import referringDomainMock from './__mocks__/ReferringDomain.json'
import retentionMock from './__mocks__/Retention.json'
import worldMapMock from './__mocks__/WorldMap.json'
import { webAnalyticsDataTableQueryContext } from './WebAnalyticsTile'

type Story = StoryObj<QueryProps<Node>>
const meta: Meta<QueryProps<Node>> = {
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
    render: (args) => {
        const { setTablesOrderBy } = useActions(webAnalyticsLogic)
        useDelayedOnMountEffect(() => setTablesOrderBy('Views' as WebAnalyticsOrderByFields, 'DESC'))

        return <Query {...args} context={{ ...webAnalyticsDataTableQueryContext }} readOnly />
    },
}
export default meta

export const WorldMap: Story = {
    args: { query: examples['WebAnalyticsWorldMap'] },
}

export const ReferrerDomain: Story = {
    args: { query: examples['WebAnalyticsReferrerDomain'] },
}

export const Path: Story = {
    args: { query: examples['WebAnalyticsPath'] },
}

export const Retention: Story = {
    args: { query: examples['WebAnalyticsRetention'] },
}

export const Browser: Story = {
    args: { query: examples['WebAnalyticsBrowser'] },
}
