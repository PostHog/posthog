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
            snapshotBrowsers: ['chromium', 'webkit'],
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
export const TrendsLine = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/trendsLine.json')
)
TrendsLine.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsLineEdit = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/trendsLine.json'),
    'edit'
)
TrendsLineEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsLineBreakdown = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/trendsLineBreakdown.json')
)
TrendsLineBreakdown.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsLineBreakdownEdit = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/trendsLineBreakdown.json'),
    'edit'
)
TrendsLineBreakdownEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsBar = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/trendsBar.json')
)
TrendsBar.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsBarEdit = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/trendsBar.json'),
    'edit'
)
TrendsBarEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsBarBreakdown = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/trendsBarBreakdown.json')
)
TrendsBarBreakdown.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsBarBreakdownEdit = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/trendsBarBreakdown.json'),
    'edit'
)
TrendsBarBreakdownEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsValue = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/trendsValue.json')
)
TrendsValue.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-bar-value-graph] > canvas' },
}
export const TrendsValueEdit = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/trendsValue.json'),
    'edit'
)
TrendsValueEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-bar-value-graph] > canvas' },
}

export const TrendsValueBreakdown = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/trendsValueBreakdown.json')
)
TrendsValueBreakdown.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-bar-value-graph] > canvas' },
}
export const TrendsValueBreakdownEdit = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/trendsValueBreakdown.json'),
    'edit'
)
TrendsValueBreakdownEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-bar-value-graph] > canvas' },
}

export const TrendsArea = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/trendsArea.json')
)
TrendsArea.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsAreaEdit = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/trendsArea.json'),
    'edit'
)
TrendsAreaEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsAreaBreakdown = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/trendsAreaBreakdown.json')
)
TrendsAreaBreakdown.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsAreaBreakdownEdit = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/trendsAreaBreakdown.json'),
    'edit'
)
TrendsAreaBreakdownEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsNumber = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/trendsNumber.json')
)
TrendsNumber.parameters = { testOptions: { waitForLoadersToDisappear: '.BoldNumber__value' } }
export const TrendsNumberEdit = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/trendsNumber.json'),
    'edit'
)
TrendsNumberEdit.parameters = { testOptions: { waitForLoadersToDisappear: '.BoldNumber__value' } }

export const TrendsTable = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/trendsTable.json')
)
TrendsTable.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=insights-table-graph] td' } }
export const TrendsTableEdit = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/trendsTable.json'),
    'edit'
)
TrendsTableEdit.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=insights-table-graph] td' } }

export const TrendsTableBreakdown = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/trendsTableBreakdown.json')
)
TrendsTableBreakdown.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=insights-table-graph] td' } }
export const TrendsTableBreakdownEdit = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/trendsTableBreakdown.json'),
    'edit'
)
TrendsTableBreakdownEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=insights-table-graph] td' },
}

export const TrendsPie = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/trendsPie.json')
)
TrendsPie.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=trend-pie-graph] > canvas' } }
export const TrendsPieEdit = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/trendsPie.json'),
    'edit'
)
TrendsPieEdit.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=trend-pie-graph] > canvas' } }

export const TrendsPieBreakdown = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/trendsPieBreakdown.json')
)
TrendsPieBreakdown.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=trend-pie-graph] > canvas' } }
export const TrendsPieBreakdownEdit = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/trendsPieBreakdown.json'),
    'edit'
)
TrendsPieBreakdownEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-pie-graph] > canvas' },
}

export const TrendsWorldMap = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/trendsWorldMap.json')
)
TrendsWorldMap.parameters = { testOptions: { waitForLoadersToDisappear: '.WorldMap' } }
export const TrendsWorldMapEdit = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/trendsWorldMap.json'),
    'edit'
)
TrendsWorldMapEdit.parameters = { testOptions: { waitForLoadersToDisappear: '.WorldMap' } }

// Funnels

export const FunnelLeftToRight = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/funnelLeftToRight.json')
)
FunnelLeftToRight.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-bar-graph] .StepBar' } }
export const FunnelLeftToRightEdit = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/funnelLeftToRight.json'),
    'edit'
)
FunnelLeftToRightEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-bar-graph] .StepBar' },
}

export const FunnelLeftToRightBreakdown = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/funnelLeftToRightBreakdown.json')
)
FunnelLeftToRightBreakdown.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-bar-graph] .StepBar' },
}
export const FunnelLeftToRightBreakdownEdit = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/funnelLeftToRightBreakdown.json'),
    'edit'
)
FunnelLeftToRightBreakdownEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-bar-graph] .StepBar' },
}

export const FunnelTopToBottom = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/funnelTopToBottom.json')
)
FunnelTopToBottom.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-bar-graph] .funnel-bar' },
}
export const FunnelTopToBottomEdit = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/funnelTopToBottom.json'),
    'edit'
)
FunnelTopToBottomEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-bar-graph] .funnel-bar' },
}

export const FunnelTopToBottomBreakdown = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/funnelTopToBottomBreakdown.json')
)
FunnelTopToBottomBreakdown.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-bar-graph] .funnel-bar' },
}
export const FunnelTopToBottomBreakdownEdit = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/funnelTopToBottomBreakdown.json'),
    'edit'
)
FunnelTopToBottomBreakdownEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-bar-graph] .funnel-bar' },
}

export const FunnelHistoricalTrends = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/funnelHistoricalTrends.json')
)
FunnelHistoricalTrends.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph-funnel] > canvas' },
}
export const FunnelHistoricalTrendsEdit = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/funnelHistoricalTrends.json'),
    'edit'
)
FunnelHistoricalTrendsEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph-funnel] > canvas' },
}

export const FunnelTimeToConvert = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/funnelTimeToConvert.json')
)
FunnelTimeToConvert.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-histogram] svg' } }
export const FunnelTimeToConvertEdit = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/funnelTimeToConvert.json'),
    'edit'
)
FunnelTimeToConvertEdit.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-histogram] svg' } }

// Retention

export const Retention = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/retention.json')
)
Retention.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}
export const RetentionEdit = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/retention.json'),
    'edit'
)
RetentionEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

export const RetentionBreakdown = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/retentionBreakdown.json')
)
RetentionBreakdown.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}
export const RetentionBreakdownEdit = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/retentionBreakdown.json'),
    'edit'
)
RetentionBreakdownEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

// Lifecycle

export const Lifecycle = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/lifecycle.json')
)
Lifecycle.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}
export const LifecycleEdit = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/lifecycle.json'),
    'edit'
)
LifecycleEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

// Stickiness

export const Stickiness = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/stickiness.json')
)
Stickiness.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}
export const StickinessEdit = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/stickiness.json'),
    'edit'
)
StickinessEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

// User Paths

export const UserPaths = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/userPaths.json')
)
UserPaths.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=paths-viz] > svg' } }
export const UserPathsEdit = createInsightStory(
    require('../../mocks/fixtures/api/projects/:team_id/insights/userPaths.json'),
    'edit'
)
UserPathsEdit.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=paths-viz] > svg' } }
/* eslint-enable @typescript-eslint/no-var-requires */
