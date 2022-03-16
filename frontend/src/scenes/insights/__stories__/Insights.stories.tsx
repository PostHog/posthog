/* eslint-disable */
import { Meta } from '@storybook/react'
import React, { useEffect } from 'react'
import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { InsightScene } from '../InsightScene'
import { router } from 'kea-router'
import { InsightModel } from '~/types'
import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__stories__/insight.mocks'

export default {
    title: 'Scenes/Insights',
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

function createInsightScene(insight: Partial<InsightModel>): () => JSX.Element {
    return function InsightStorybookScene() {
        useStorybookMocks({
            get: {
                '/api/projects/:projectId/insights/': (_, __, ctx) => [
                    ctx.delay(100),
                    ctx.status(200),
                    ctx.json({ count: 1, results: [insight] }),
                ],
            },
        })

        useEffect(() => {
            router.actions.push(`/insights/${insight.short_id}`)
        }, [])

        return <InsightScene />
    }
}

export const TrendsLine = createInsightScene(require('./trendsLine.json'))
export const TrendsLineBreakdown = createInsightScene(require('./trendsLineBreakdown.json'))
export const TrendsBar = createInsightScene(require('./trendsBar.json'))
export const TrendsBarBreakdown = createInsightScene(require('./trendsBarBreakdown.json'))
export const TrendsValue = createInsightScene(require('./trendsValue.json'))
export const TrendsValueBreakdown = createInsightScene(require('./trendsValueBreakdown.json'))
export const TrendsTable = createInsightScene(require('./trendsTable.json'))
export const TrendsTableBreakdown = createInsightScene(require('./trendsTableBreakdown.json'))
export const TrendsPie = createInsightScene(require('./trendsPie.json'))
export const TrendsPieBreakdown = createInsightScene(require('./trendsPieBreakdown.json'))

export const FunnelLeftToRight = createInsightScene(require('./funnelLeftToRight.json'))
export const FunnelLeftToRightBreakdown = createInsightScene(require('./funnelLeftToRightBreakdown.json'))
export const FunnelTopToBottom = createInsightScene(require('./funnelTopToBottom.json'))
export const FunnelTopToBottomBreakdown = createInsightScene(require('./funnelTopToBottomBreakdown.json'))
export const funnelHistoricalTrends = createInsightScene(require('./funnelHistoricalTrends.json'))
export const FunnelTimeToConvert = createInsightScene(require('./funnelTimeToConvert.json'))

export const Retention = createInsightScene(require('./retention.json'))
export const RetentionBreakdown = createInsightScene(require('./retentionBreakdown.json'))
export const Lifecycle = createInsightScene(require('./lifecycle.json'))
export const Stickiness = createInsightScene(require('./stickiness.json'))
export const UserPaths = createInsightScene(require('./userPaths.json'))
