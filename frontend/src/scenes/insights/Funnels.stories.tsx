import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { Meta, StoryObj } from '@storybook/react'
import { userEvent, waitFor } from '@storybook/testing-library'

import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { mswDecorator } from '~/mocks/browser'

type Story = StoryObj<{}>
const meta: Meta = {
    title: 'Scenes-App/Insights/Funnels',
    parameters: {
        layout: 'fullscreen',
        testOptions: {
            snapshotBrowsers: ['chromium'],
            viewport: {
                // needs a slightly larger width to push the rendered scene away from the breakpoint boundary
                width: 1300,
                height: 720,
            },
        },
        viewMode: 'story',
        mockDate: '2022-03-11',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/persons/retention': sampleRetentionPeopleResponse,
                '/api/environments/:team_id/persons/properties': samplePersonProperties,
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

// Funnels

// FLAP!
// export const FunnelLeftToRight: Story = createInsightStory(
//     require('../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRight.json')
// )
// FunnelLeftToRight.parameters = {
//     testOptions: { waitForSelector: ['[data-attr=funnel-bar-vertical] .StepBar', '.PayGateMini'] },
// }
export const FunnelLeftToRightEdit: Story = createInsightStory(
    require('../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRight.json'),
    'edit'
)
FunnelLeftToRightEdit.parameters = {
    testOptions: { waitForSelector: ['[data-attr=funnel-bar-vertical] .StepBar', '.PayGateMini'] },
}

export const FunnelLeftToRightBreakdown: Story = createInsightStory(
    require('../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRightBreakdown.json')
)
FunnelLeftToRightBreakdown.parameters = {
    testOptions: { waitForSelector: ['[data-attr=funnel-bar-vertical] .StepBar', '.PayGateMini'] },
}
export const FunnelLeftToRightBreakdownEdit: Story = createInsightStory(
    require('../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRightBreakdown.json'),
    'edit'
)
FunnelLeftToRightBreakdownEdit.parameters = {
    testOptions: { waitForSelector: ['[data-attr=funnel-bar-vertical] .StepBar', '.PayGateMini'] },
}
export const FunnelTopToBottom: Story = createInsightStory(
    require('../../mocks/fixtures/api/projects/team_id/insights/funnelTopToBottom.json')
)
FunnelTopToBottom.parameters = {
    testOptions: { waitForSelector: ['[data-attr=funnel-bar-horizontal] > .funnel-step'] },
}
export const FunnelTopToBottomEdit: Story = createInsightStory(
    require('../../mocks/fixtures/api/projects/team_id/insights/funnelTopToBottom.json'),
    'edit'
)
FunnelTopToBottomEdit.parameters = {
    testOptions: { waitForSelector: ['[data-attr=funnel-bar-horizontal] > .funnel-step'] },
}
export const FunnelTopToBottomBreakdown: Story = createInsightStory(
    require('../../mocks/fixtures/api/projects/team_id/insights/funnelTopToBottomBreakdown.json')
)
FunnelTopToBottomBreakdown.parameters = {
    testOptions: { waitForSelector: ['[data-attr=funnel-bar-horizontal] > .funnel-step'] },
}
export const FunnelTopToBottomBreakdownEdit: Story = createInsightStory(
    require('../../mocks/fixtures/api/projects/team_id/insights/funnelTopToBottomBreakdown.json'),
    'edit'
)
FunnelTopToBottomBreakdownEdit.parameters = {
    testOptions: { waitForSelector: ['[data-attr=funnel-bar-horizontal] > .funnel-step'] },
}
export const FunnelHistoricalTrends: Story = createInsightStory(
    require('../../mocks/fixtures/api/projects/team_id/insights/funnelHistoricalTrends.json')
)
FunnelHistoricalTrends.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph-funnel] > canvas' },
}
export const FunnelHistoricalTrendsEdit: Story = createInsightStory(
    require('../../mocks/fixtures/api/projects/team_id/insights/funnelHistoricalTrends.json'),
    'edit'
)
FunnelHistoricalTrendsEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph-funnel] > canvas' },
}

export const FunnelTimeToConvert: Story = createInsightStory(
    require('../../mocks/fixtures/api/projects/team_id/insights/funnelTimeToConvert.json')
)
FunnelTimeToConvert.parameters = { testOptions: { waitForSelector: '[data-attr=funnel-histogram] svg' } }
export const FunnelTimeToConvertEdit: Story = createInsightStory(
    require('../../mocks/fixtures/api/projects/team_id/insights/funnelTimeToConvert.json'),
    'edit'
)
FunnelTimeToConvertEdit.parameters = { testOptions: { waitForSelector: '[data-attr=funnel-histogram] svg' } }

export const FunnelWithInlineEventsEdit: Story = createInsightStory(
    require('../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRightWithInlineEvents.json'),
    'edit'
)
FunnelWithInlineEventsEdit.parameters = {
    testOptions: { waitForSelector: ['[data-attr=funnel-bar-vertical] .StepBar', '.PayGateMini'] },
}
FunnelWithInlineEventsEdit.play = async ({ canvasElement }) => {
    const expandFiltersButton = await waitFor(
        () => {
            const filtersButton = canvasElement.querySelector<HTMLElement>('[data-attr="show-prop-filter-0"]')
            if (!filtersButton) {
                throw new Error('Filters button not yet rendered')
            }
            return filtersButton
        },
        { timeout: 2000 }
    )
    await userEvent.click(expandFiltersButton)
}

export const FunnelLeftToRightEditViewports: Story = createInsightStory(
    require('../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRight.json'),
    'edit'
)
const waitForFunnelToStabilize: NonNullable<Story['play']> = async ({ canvasElement }) => {
    let lastHeight = 0
    await waitFor(
        () => {
            const funnelContainer = canvasElement.querySelector('[data-attr=funnel-bar-vertical]')
            const currentHeight = funnelContainer ? funnelContainer.getBoundingClientRect().height : 0
            if (currentHeight === 0 || currentHeight !== lastHeight) {
                lastHeight = currentHeight
                throw new Error('funnel height not yet stable')
            }
        },
        { timeout: 3000, interval: 200 }
    )
}
FunnelLeftToRightEditViewports.parameters = {
    testOptions: {
        waitForSelector: ['[data-attr=funnel-bar-vertical] .StepBar', '.PayGateMini'],
        viewportWidths: ['medium', 'wide', 'superwide'],
    },
}
FunnelLeftToRightEditViewports.play = waitForFunnelToStabilize

/* eslint-enable @typescript-eslint/no-var-requires */
