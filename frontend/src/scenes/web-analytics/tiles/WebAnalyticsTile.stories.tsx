import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'
import { worldMapLogic } from 'scenes/insights/views/WorldMap/worldMapLogic'

import { mswDecorator } from '~/mocks/browser'
import { examples } from '~/queries/examples'
import { Query } from '~/queries/Query/Query'

import browserMock from './__mocks__/Browser.json'
import pathMock from './__mocks__/Path.json'
import referringDomainMock from './__mocks__/ReferringDomain.json'
import retentionMock from './__mocks__/Retention.json'
import worldMapMock from './__mocks__/WorldMap.json'
import { webAnalyticsDataTableQueryContext } from './WebAnalyticsTile'

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

const SimpleQueryTemplate: StoryFn<typeof Query> = (args) => {
    return <Query {...args} context={{ ...webAnalyticsDataTableQueryContext }} readOnly />
}

const WorldMapTemplate: StoryFn<typeof Query> = (args) => {
    // TODO: Use the other functions, see below
    // const { showTooltip, hideTooltip, updateTooltipCoordinates } = useActions(worldMapLogic({ dashboardItemId: `new-AdHoc.InsightViz.${args.uniqueKey}` }))
    const { showTooltip } = useActions(worldMapLogic({ dashboardItemId: `new-AdHoc.InsightViz.${args.uniqueKey}` }))

    useEffect(() => {
        if (args.uniqueKey === 'new-world-map') {
            // @ts-expect-error - the code doesn't need to know the extra TrendResult keys besides the agg_value
            showTooltip('GB', { aggregated_value: 2702 })

            // TODO: Add this back in, it's breaking the snapshots by displaying the tooltip
            // in some follow-up stories, it's not clear why the `hideTooltip` call is not working
            // Can be reproduced locally very easily
            // updateTooltipCoordinates(380, 90)
        }

        // Hide tooltip when unmounting
        // TODO: Add this back in, see above
        // return hideTooltip
    }, []) // eslint-disable-line react-hooks/exhaustive-deps

    // NOTE: Hardcoding width/height to make sure the world map is rendered properly
    // and that the (380, 90) coordinates are correct and near GB
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ width: '800px', height: '600px' }}>
            <Query {...args} readOnly />
        </div>
    )
}

export const WorldMap: Story = WorldMapTemplate.bind({})
WorldMap.args = { query: examples['WebAnalyticsWorldMap'], uniqueKey: 'new-world-map' }

export const ReferrerDomain: Story = SimpleQueryTemplate.bind({})
ReferrerDomain.args = { query: examples['WebAnalyticsReferrerDomain'] }

export const Path: Story = SimpleQueryTemplate.bind({})
Path.args = { query: examples['WebAnalyticsPath'] }

export const Retention: Story = SimpleQueryTemplate.bind({})
Retention.args = { query: examples['WebAnalyticsRetention'] }

export const Browser: Story = SimpleQueryTemplate.bind({})
Browser.args = { query: examples['WebAnalyticsBrowser'] }
