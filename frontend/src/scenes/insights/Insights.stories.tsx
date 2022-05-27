import { Meta } from '@storybook/react'
import { mswDecorator } from '~/mocks/browser'
import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'
import { createInsightScene } from 'scenes/insights/__mocks__/createInsightScene'

export default {
    title: 'Scenes-App/Insights',
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'canvas' },
    decorators: [
        mswDecorator({
            get: {
                '/api/person/retention': sampleRetentionPeopleResponse,
                '/api/person/properties': samplePersonProperties,
            },
            post: {
                '/api/projects/:projectId/cohorts/': { id: 1 },
            },
        }),
    ],
} as Meta

/* eslint-disable @typescript-eslint/no-var-requires */
export const TrendsLine = createInsightScene(require('./__mocks__/trendsLine.json'))
export const TrendsLineBreakdown = createInsightScene(require('./__mocks__/trendsLineBreakdown.json'))
export const TrendsBar = createInsightScene(require('./__mocks__/trendsBar.json'))
export const TrendsBarBreakdown = createInsightScene(require('./__mocks__/trendsBarBreakdown.json'))
export const TrendsWorldMap = createInsightScene(require('./__mocks__/trendsWorldMap.json'))
export const TrendsValue = createInsightScene(require('./__mocks__/trendsValue.json'))
export const TrendsValueBreakdown = createInsightScene(require('./__mocks__/trendsValueBreakdown.json'))
export const TrendsTable = createInsightScene(require('./__mocks__/trendsTable.json'))
export const TrendsTableBreakdown = createInsightScene(require('./__mocks__/trendsTableBreakdown.json'))
export const TrendsPie = createInsightScene(require('./__mocks__/trendsPie.json'))
export const TrendsPieBreakdown = createInsightScene(require('./__mocks__/trendsPieBreakdown.json'))

export const FunnelLeftToRight = createInsightScene(require('./__mocks__/funnelLeftToRight.json'))
export const FunnelLeftToRightBreakdown = createInsightScene(require('./__mocks__/funnelLeftToRightBreakdown.json'))
export const FunnelTopToBottom = createInsightScene(require('./__mocks__/funnelTopToBottom.json'))
export const FunnelTopToBottomBreakdown = createInsightScene(require('./__mocks__/funnelTopToBottomBreakdown.json'))
export const FunnelHistoricalTrends = createInsightScene(require('./__mocks__/funnelHistoricalTrends.json'))
export const FunnelTimeToConvert = createInsightScene(require('./__mocks__/funnelTimeToConvert.json'))

export const Retention = createInsightScene(require('./__mocks__/retention.json'))
export const RetentionBreakdown = createInsightScene(require('./__mocks__/retentionBreakdown.json'))
export const Lifecycle = createInsightScene(require('./__mocks__/lifecycle.json'))
export const Stickiness = createInsightScene(require('./__mocks__/stickiness.json'))
export const UserPaths = createInsightScene(require('./__mocks__/userPaths.json'))
/* eslint-enable @typescript-eslint/no-var-requires */
