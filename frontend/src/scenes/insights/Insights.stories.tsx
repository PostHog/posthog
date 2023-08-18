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
                '/api/projects/:team_id/groups_types': [],
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
export const TrendsLineEdit = createInsightStory(require('./__mocks__/trendsLine.json'), 'edit')
TrendsLineEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsLineBreakdown = createInsightStory(require('./__mocks__/trendsLineBreakdown.json'))
TrendsLineBreakdown.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsLineBreakdownEdit = createInsightStory(require('./__mocks__/trendsLineBreakdown.json'), 'edit')
TrendsLineBreakdownEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsBar = createInsightStory(require('./__mocks__/trendsBar.json'))
TrendsBar.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsBarEdit = createInsightStory(require('./__mocks__/trendsBar.json'), 'edit')
TrendsBarEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsBarBreakdown = createInsightStory(require('./__mocks__/trendsBarBreakdown.json'))
TrendsBarBreakdown.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsBarBreakdownEdit = createInsightStory(require('./__mocks__/trendsBarBreakdown.json'), 'edit')
TrendsBarBreakdownEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsValue = createInsightStory(require('./__mocks__/trendsValue.json'))
TrendsValue.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-bar-value-graph] > canvas' },
}
export const TrendsValueEdit = createInsightStory(require('./__mocks__/trendsValue.json'), 'edit')
TrendsValueEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-bar-value-graph] > canvas' },
}

export const TrendsValueBreakdown = createInsightStory(require('./__mocks__/trendsValueBreakdown.json'))
TrendsValueBreakdown.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-bar-value-graph] > canvas' },
}
export const TrendsValueBreakdownEdit = createInsightStory(require('./__mocks__/trendsValueBreakdown.json'), 'edit')
TrendsValueBreakdownEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-bar-value-graph] > canvas' },
}

export const TrendsArea = createInsightStory(require('./__mocks__/trendsArea.json'))
TrendsArea.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsAreaEdit = createInsightStory(require('./__mocks__/trendsArea.json'), 'edit')
TrendsAreaEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsAreaBreakdown = createInsightStory(require('./__mocks__/trendsAreaBreakdown.json'))
TrendsAreaBreakdown.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsAreaBreakdownEdit = createInsightStory(require('./__mocks__/trendsAreaBreakdown.json'), 'edit')
TrendsAreaBreakdownEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsNumber = createInsightStory(require('./__mocks__/trendsNumber.json'))
TrendsNumber.parameters = { testOptions: { waitForLoadersToDisappear: '.BoldNumber__value' } }
export const TrendsNumberEdit = createInsightStory(require('./__mocks__/trendsNumber.json'), 'edit')
TrendsNumberEdit.parameters = { testOptions: { waitForLoadersToDisappear: '.BoldNumber__value' } }

export const TrendsTable = createInsightStory(require('./__mocks__/trendsTable.json'))
TrendsTable.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=insights-table-graph] td' } }
export const TrendsTableEdit = createInsightStory(require('./__mocks__/trendsTable.json'), 'edit')
TrendsTableEdit.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=insights-table-graph] td' } }

export const TrendsTableBreakdown = createInsightStory(require('./__mocks__/trendsTableBreakdown.json'))
TrendsTableBreakdown.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=insights-table-graph] td' } }
export const TrendsTableBreakdownEdit = createInsightStory(require('./__mocks__/trendsTableBreakdown.json'), 'edit')
TrendsTableBreakdownEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=insights-table-graph] td' },
}

export const TrendsPie = createInsightStory(require('./__mocks__/trendsPie.json'))
TrendsPie.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=trend-pie-graph] > canvas' } }
export const TrendsPieEdit = createInsightStory(require('./__mocks__/trendsPie.json'), 'edit')
TrendsPieEdit.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=trend-pie-graph] > canvas' } }

export const TrendsPieBreakdown = createInsightStory(require('./__mocks__/trendsPieBreakdown.json'))
TrendsPieBreakdown.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=trend-pie-graph] > canvas' } }
export const TrendsPieBreakdownEdit = createInsightStory(require('./__mocks__/trendsPieBreakdown.json'), 'edit')
TrendsPieBreakdownEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-pie-graph] > canvas' },
}

export const TrendsWorldMap = createInsightStory(require('./__mocks__/trendsWorldMap.json'))
TrendsWorldMap.parameters = { testOptions: { waitForLoadersToDisappear: '.WorldMap' } }
export const TrendsWorldMapEdit = createInsightStory(require('./__mocks__/trendsWorldMap.json'), 'edit')
TrendsWorldMapEdit.parameters = { testOptions: { waitForLoadersToDisappear: '.WorldMap' } }

// Funnels

export const FunnelLeftToRight = createInsightStory(require('./__mocks__/funnelLeftToRight.json'))
FunnelLeftToRight.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-bar-graph] .StepBar' } }
export const FunnelLeftToRightEdit = createInsightStory(require('./__mocks__/funnelLeftToRight.json'), 'edit')
FunnelLeftToRightEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-bar-graph] .StepBar' },
}

export const FunnelLeftToRightBreakdown = createInsightStory(require('./__mocks__/funnelLeftToRightBreakdown.json'))
FunnelLeftToRightBreakdown.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-bar-graph] .StepBar' },
}
export const FunnelLeftToRightBreakdownEdit = createInsightStory(
    require('./__mocks__/funnelLeftToRightBreakdown.json'),
    'edit'
)
FunnelLeftToRightBreakdownEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-bar-graph] .StepBar' },
}

export const FunnelTopToBottom = createInsightStory(require('./__mocks__/funnelTopToBottom.json'))
FunnelTopToBottom.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-bar-graph] .funnel-bar' },
}
export const FunnelTopToBottomEdit = createInsightStory(require('./__mocks__/funnelTopToBottom.json'), 'edit')
FunnelTopToBottomEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-bar-graph] .funnel-bar' },
}

export const FunnelTopToBottomBreakdown = createInsightStory(require('./__mocks__/funnelTopToBottomBreakdown.json'))
FunnelTopToBottomBreakdown.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-bar-graph] .funnel-bar' },
}
export const FunnelTopToBottomBreakdownEdit = createInsightStory(
    require('./__mocks__/funnelTopToBottomBreakdown.json'),
    'edit'
)
FunnelTopToBottomBreakdownEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-bar-graph] .funnel-bar' },
}

export const FunnelHistoricalTrends = createInsightStory(require('./__mocks__/funnelHistoricalTrends.json'))
FunnelHistoricalTrends.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph-funnel] > canvas' },
}
export const FunnelHistoricalTrendsEdit = createInsightStory(require('./__mocks__/funnelHistoricalTrends.json'), 'edit')
FunnelHistoricalTrendsEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph-funnel] > canvas' },
}

export const FunnelTimeToConvert = createInsightStory(require('./__mocks__/funnelTimeToConvert.json'))
FunnelTimeToConvert.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-histogram] svg' } }
export const FunnelTimeToConvertEdit = createInsightStory(require('./__mocks__/funnelTimeToConvert.json'), 'edit')
FunnelTimeToConvertEdit.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-histogram] svg' } }

// Retention

export const Retention = createInsightStory(require('./__mocks__/retention.json'))
Retention.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}
export const RetentionEdit = createInsightStory(require('./__mocks__/retention.json'), 'edit')
RetentionEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

export const RetentionBreakdown = createInsightStory(require('./__mocks__/retentionBreakdown.json'))
RetentionBreakdown.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}
export const RetentionBreakdownEdit = createInsightStory(require('./__mocks__/retentionBreakdown.json'), 'edit')
RetentionBreakdownEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

// Lifecycle

export const Lifecycle = createInsightStory(require('./__mocks__/lifecycle.json'))
Lifecycle.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}
export const LifecycleEdit = createInsightStory(require('./__mocks__/lifecycle.json'), 'edit')
LifecycleEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

// Stickiness

export const Stickiness = createInsightStory(require('./__mocks__/stickiness.json'))
Stickiness.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}
export const StickinessEdit = createInsightStory(require('./__mocks__/stickiness.json'), 'edit')
StickinessEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

// User Paths

export const UserPaths = createInsightStory(require('./__mocks__/userPaths.json'))
UserPaths.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=paths-viz] > svg' } }
export const UserPathsEdit = createInsightStory(require('./__mocks__/userPaths.json'), 'edit')
UserPathsEdit.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=paths-viz] > svg' } }
/* eslint-enable @typescript-eslint/no-var-requires */
