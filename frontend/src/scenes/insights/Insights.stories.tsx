import { Meta } from '@storybook/react'
import { mswDecorator } from '~/mocks/browser'
import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'
import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

export default {
    title: 'Scenes-App/Insights',
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
        testOptions: {
            excludeNavigationFromSnapshot: true,
            snapshotBrowsers: ['chromium', 'webkit', 'firefox'],
        },
        viewMode: 'story',
        mockDate: '2022-03-11',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/persons/retention': sampleRetentionPeopleResponse,
                '/api/projects/:team_id/persons/properties': samplePersonProperties,
            },
            post: {
                '/api/projects/:team_id/cohorts/': { id: 1 },
            },
        }),
    ],
} as Meta

/* eslint-disable @typescript-eslint/no-var-requires */
// Trends
export const TrendsLine = createInsightStory(require('./__mocks__/trendsLine.json'))
TrendsLine.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsLineBreakdown = createInsightStory(require('./__mocks__/trendsLineBreakdown.json'))
TrendsLineBreakdown.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsBar = createInsightStory(require('./__mocks__/trendsBar.json'))
TrendsBar.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsBarBreakdown = createInsightStory(require('./__mocks__/trendsBarBreakdown.json'))
TrendsBarBreakdown.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsValue = createInsightStory(require('./__mocks__/trendsValue.json'))
TrendsValue.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-bar-value-graph] > canvas' },
}

export const TrendsValueBreakdown = createInsightStory(require('./__mocks__/trendsValueBreakdown.json'))
TrendsValueBreakdown.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-bar-value-graph] > canvas' },
}
export const TrendsArea = createInsightStory(require('./__mocks__/trendsArea.json'))
TrendsArea.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsAreaBreakdown = createInsightStory(require('./__mocks__/trendsAreaBreakdown.json'))
TrendsAreaBreakdown.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsNumber = createInsightStory(require('./__mocks__/trendsNumber.json'))
TrendsNumber.parameters = { testOptions: { waitForLoadersToDisappear: '.BoldNumber__value' } }

export const TrendsTable = createInsightStory(require('./__mocks__/trendsTable.json'))
TrendsTable.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=insights-table-graph] td' } }

export const TrendsTableBreakdown = createInsightStory(require('./__mocks__/trendsTableBreakdown.json'))
TrendsTableBreakdown.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=insights-table-graph] td' } }

export const TrendsPie = createInsightStory(require('./__mocks__/trendsPie.json'))
TrendsPie.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=trend-pie-graph] > canvas' } }

export const TrendsPieBreakdown = createInsightStory(require('./__mocks__/trendsPieBreakdown.json'))
TrendsPieBreakdown.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=trend-pie-graph] > canvas' } }

export const TrendsWorldMap = createInsightStory(require('./__mocks__/trendsWorldMap.json'))
TrendsWorldMap.parameters = { testOptions: { waitForLoadersToDisappear: '.WorldMap' } }

// Funnels

export const FunnelLeftToRight = createInsightStory(require('./__mocks__/funnelLeftToRight.json'))
FunnelLeftToRight.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-bar-graph] .StepBar' } }

export const FunnelLeftToRightBreakdown = createInsightStory(require('./__mocks__/funnelLeftToRightBreakdown.json'))
FunnelLeftToRightBreakdown.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-bar-graph] .StepBar' },
}

export const FunnelTopToBottom = createInsightStory(require('./__mocks__/funnelTopToBottom.json'))
FunnelTopToBottom.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-bar-graph] .funnel-bar' },
}

export const FunnelTopToBottomBreakdown = createInsightStory(require('./__mocks__/funnelTopToBottomBreakdown.json'))
FunnelTopToBottomBreakdown.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-bar-graph] .funnel-bar' },
}

export const FunnelHistoricalTrends = createInsightStory(require('./__mocks__/funnelHistoricalTrends.json'))
FunnelHistoricalTrends.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph-funnel] > canvas' },
}

export const FunnelTimeToConvert = createInsightStory(require('./__mocks__/funnelTimeToConvert.json'))
FunnelTimeToConvert.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-histogram] svg' } }

// Retention

export const Retention = createInsightStory(require('./__mocks__/retention.json'))
Retention.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

export const RetentionBreakdown = createInsightStory(require('./__mocks__/retentionBreakdown.json'))
RetentionBreakdown.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

// Lifecycle

export const Lifecycle = createInsightStory(require('./__mocks__/lifecycle.json'))
Lifecycle.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

// Stickiness

export const Stickiness = createInsightStory(require('./__mocks__/stickiness.json'))
Stickiness.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

// User Paths

export const UserPaths = createInsightStory(require('./__mocks__/userPaths.json'))
UserPaths.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=paths-viz] > svg' } }
/* eslint-enable @typescript-eslint/no-var-requires */
