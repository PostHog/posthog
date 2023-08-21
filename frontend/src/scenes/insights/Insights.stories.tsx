import { Meta, StoryObj } from '@storybook/react'
import { mswDecorator } from '~/mocks/browser'
import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'
import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'
import { App } from 'scenes/App'

type Story = StoryObj<typeof App>
const meta: Meta = {
    title: 'Scenes-App/Insights',
    parameters: {
        layout: 'fullscreen',
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
}
export default meta
/* eslint-disable @typescript-eslint/no-var-requires */
// Trends
export const TrendsLine: Story = createInsightStory(require('./__mocks__/trendsLine.json'))
TrendsLine.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsLineEdit: Story = createInsightStory(require('./__mocks__/trendsLine.json'), 'edit')
TrendsLineEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsLineBreakdown: Story = createInsightStory(require('./__mocks__/trendsLineBreakdown.json'))
TrendsLineBreakdown.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsLineBreakdownEdit: Story = createInsightStory(
    require('./__mocks__/trendsLineBreakdown.json'),
    'edit'
)
TrendsLineBreakdownEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsBar: Story = createInsightStory(require('./__mocks__/trendsBar.json'))
TrendsBar.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsBarEdit: Story = createInsightStory(require('./__mocks__/trendsBar.json'), 'edit')
TrendsBarEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsBarBreakdown: Story = createInsightStory(require('./__mocks__/trendsBarBreakdown.json'))
TrendsBarBreakdown.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsBarBreakdownEdit: Story = createInsightStory(require('./__mocks__/trendsBarBreakdown.json'), 'edit')
TrendsBarBreakdownEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsValue: Story = createInsightStory(require('./__mocks__/trendsValue.json'))
TrendsValue.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-bar-value-graph] > canvas' },
}
export const TrendsValueEdit: Story = createInsightStory(require('./__mocks__/trendsValue.json'), 'edit')
TrendsValueEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-bar-value-graph] > canvas' },
}

export const TrendsValueBreakdown: Story = createInsightStory(require('./__mocks__/trendsValueBreakdown.json'))
TrendsValueBreakdown.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-bar-value-graph] > canvas' },
}
export const TrendsValueBreakdownEdit: Story = createInsightStory(
    require('./__mocks__/trendsValueBreakdown.json'),
    'edit'
)
TrendsValueBreakdownEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-bar-value-graph] > canvas' },
}

export const TrendsArea: Story = createInsightStory(require('./__mocks__/trendsArea.json'))
TrendsArea.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsAreaEdit: Story = createInsightStory(require('./__mocks__/trendsArea.json'), 'edit')
TrendsAreaEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsAreaBreakdown: Story = createInsightStory(require('./__mocks__/trendsAreaBreakdown.json'))
TrendsAreaBreakdown.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsAreaBreakdownEdit: Story = createInsightStory(
    require('./__mocks__/trendsAreaBreakdown.json'),
    'edit'
)
TrendsAreaBreakdownEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsNumber: Story = createInsightStory(require('./__mocks__/trendsNumber.json'))
TrendsNumber.parameters = { testOptions: { waitForLoadersToDisappear: '.BoldNumber__value' } }
export const TrendsNumberEdit: Story = createInsightStory(require('./__mocks__/trendsNumber.json'), 'edit')
TrendsNumberEdit.parameters = { testOptions: { waitForLoadersToDisappear: '.BoldNumber__value' } }

export const TrendsTable: Story = createInsightStory(require('./__mocks__/trendsTable.json'))
TrendsTable.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=insights-table-graph] td' } }
export const TrendsTableEdit: Story = createInsightStory(require('./__mocks__/trendsTable.json'), 'edit')
TrendsTableEdit.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=insights-table-graph] td' } }

export const TrendsTableBreakdown: Story = createInsightStory(require('./__mocks__/trendsTableBreakdown.json'))
TrendsTableBreakdown.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=insights-table-graph] td' } }
export const TrendsTableBreakdownEdit: Story = createInsightStory(
    require('./__mocks__/trendsTableBreakdown.json'),
    'edit'
)
TrendsTableBreakdownEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=insights-table-graph] td' },
}

export const TrendsPie: Story = createInsightStory(require('./__mocks__/trendsPie.json'))
TrendsPie.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=trend-pie-graph] > canvas' } }
export const TrendsPieEdit: Story = createInsightStory(require('./__mocks__/trendsPie.json'), 'edit')
TrendsPieEdit.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=trend-pie-graph] > canvas' } }

export const TrendsPieBreakdown: Story = createInsightStory(require('./__mocks__/trendsPieBreakdown.json'))
TrendsPieBreakdown.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=trend-pie-graph] > canvas' } }
export const TrendsPieBreakdownEdit: Story = createInsightStory(require('./__mocks__/trendsPieBreakdown.json'), 'edit')
TrendsPieBreakdownEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-pie-graph] > canvas' },
}

export const TrendsWorldMap: Story = createInsightStory(require('./__mocks__/trendsWorldMap.json'))
TrendsWorldMap.parameters = { testOptions: { waitForLoadersToDisappear: '.WorldMap' } }
export const TrendsWorldMapEdit: Story = createInsightStory(require('./__mocks__/trendsWorldMap.json'), 'edit')
TrendsWorldMapEdit.parameters = { testOptions: { waitForLoadersToDisappear: '.WorldMap' } }

// Funnels

export const FunnelLeftToRight: Story = createInsightStory(require('./__mocks__/funnelLeftToRight.json'))
FunnelLeftToRight.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-bar-graph] .StepBar' } }
export const FunnelLeftToRightEdit: Story = createInsightStory(require('./__mocks__/funnelLeftToRight.json'), 'edit')
FunnelLeftToRightEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-bar-graph] .StepBar' },
}

export const FunnelLeftToRightBreakdown: Story = createInsightStory(
    require('./__mocks__/funnelLeftToRightBreakdown.json')
)
FunnelLeftToRightBreakdown.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-bar-graph] .StepBar' },
}
export const FunnelLeftToRightBreakdownEdit: Story = createInsightStory(
    require('./__mocks__/funnelLeftToRightBreakdown.json'),
    'edit'
)
FunnelLeftToRightBreakdownEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-bar-graph] .StepBar' },
}

export const FunnelTopToBottom: Story = createInsightStory(require('./__mocks__/funnelTopToBottom.json'))
FunnelTopToBottom.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-bar-graph] .funnel-bar' },
}
export const FunnelTopToBottomEdit: Story = createInsightStory(require('./__mocks__/funnelTopToBottom.json'), 'edit')
FunnelTopToBottomEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-bar-graph] .funnel-bar' },
}

export const FunnelTopToBottomBreakdown: Story = createInsightStory(
    require('./__mocks__/funnelTopToBottomBreakdown.json')
)
FunnelTopToBottomBreakdown.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-bar-graph] .funnel-bar' },
}
export const FunnelTopToBottomBreakdownEdit: Story = createInsightStory(
    require('./__mocks__/funnelTopToBottomBreakdown.json'),
    'edit'
)
FunnelTopToBottomBreakdownEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-bar-graph] .funnel-bar' },
}

export const FunnelHistoricalTrends: Story = createInsightStory(require('./__mocks__/funnelHistoricalTrends.json'))
FunnelHistoricalTrends.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph-funnel] > canvas' },
}
export const FunnelHistoricalTrendsEdit: Story = createInsightStory(
    require('./__mocks__/funnelHistoricalTrends.json'),
    'edit'
)
FunnelHistoricalTrendsEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph-funnel] > canvas' },
}

export const FunnelTimeToConvert: Story = createInsightStory(require('./__mocks__/funnelTimeToConvert.json'))
FunnelTimeToConvert.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-histogram] svg' } }
export const FunnelTimeToConvertEdit: Story = createInsightStory(
    require('./__mocks__/funnelTimeToConvert.json'),
    'edit'
)
FunnelTimeToConvertEdit.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=funnel-histogram] svg' } }

// Retention

export const Retention: Story = createInsightStory(require('./__mocks__/retention.json'))
Retention.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}
export const RetentionEdit: Story = createInsightStory(require('./__mocks__/retention.json'), 'edit')
RetentionEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

export const RetentionBreakdown: Story = createInsightStory(require('./__mocks__/retentionBreakdown.json'))
RetentionBreakdown.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}
export const RetentionBreakdownEdit: Story = createInsightStory(require('./__mocks__/retentionBreakdown.json'), 'edit')
RetentionBreakdownEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

// Lifecycle

export const Lifecycle: Story = createInsightStory(require('./__mocks__/lifecycle.json'))
Lifecycle.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}
export const LifecycleEdit: Story = createInsightStory(require('./__mocks__/lifecycle.json'), 'edit')
LifecycleEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

// Stickiness

export const Stickiness: Story = createInsightStory(require('./__mocks__/stickiness.json'))
Stickiness.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}
export const StickinessEdit: Story = createInsightStory(require('./__mocks__/stickiness.json'), 'edit')
StickinessEdit.parameters = {
    testOptions: { waitForLoadersToDisappear: '[data-attr=trend-line-graph] > canvas' },
}

// User Paths

export const UserPaths: Story = createInsightStory(require('./__mocks__/userPaths.json'))
UserPaths.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=paths-viz] > svg' } }
export const UserPathsEdit: Story = createInsightStory(require('./__mocks__/userPaths.json'), 'edit')
UserPathsEdit.parameters = { testOptions: { waitForLoadersToDisappear: '[data-attr=paths-viz] > svg' } }
/* eslint-enable @typescript-eslint/no-var-requires */
