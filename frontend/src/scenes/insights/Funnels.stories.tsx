import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { mswDecorator } from '~/mocks/browser'

import __funnelHistoricalTrends from '../../mocks/fixtures/api/projects/team_id/insights/funnelHistoricalTrends.json'
import __funnelHistoricalTrendsCompare from '../../mocks/fixtures/api/projects/team_id/insights/funnelHistoricalTrendsCompare.json'
import __funnelLeftToRight from '../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRight.json'
import __funnelLeftToRightBreakdown from '../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRightBreakdown.json'
import __funnelLeftToRightCompare from '../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRightCompare.json'
import __funnelLeftToRightWithInlineEvents from '../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRightWithInlineEvents.json'
import __funnelTimeToConvert from '../../mocks/fixtures/api/projects/team_id/insights/funnelTimeToConvert.json'
import __funnelTopToBottom from '../../mocks/fixtures/api/projects/team_id/insights/funnelTopToBottom.json'
import __funnelTopToBottomBreakdown from '../../mocks/fixtures/api/projects/team_id/insights/funnelTopToBottomBreakdown.json'

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

const waitForFunnelToStabilize: NonNullable<Story['play']> = async ({ canvasElement }) => {
    let lastHeight = 0
    await waitFor(
        () => {
            const funnelContainer = canvasElement.querySelector('[data-attr=funnel-steps-bar-chart]')
            const currentHeight = funnelContainer ? funnelContainer.getBoundingClientRect().height : 0
            if (currentHeight === 0 || currentHeight !== lastHeight) {
                lastHeight = currentHeight
                throw new Error('funnel height not yet stable')
            }
        },
        { timeout: 3000, interval: 200 }
    )
}

// FLAP!
// export const FunnelLeftToRight: Story = createInsightStory(
//     __funnelLeftToRight
// )
// FunnelLeftToRight.parameters = {
//     testOptions: { waitForSelector: ['[data-attr=funnel-steps-bar-chart] canvas[role="img"]', '.PayGateMini'] },
// }
export const FunnelLeftToRightEdit: Story = createInsightStory(__funnelLeftToRight as any, 'edit')
FunnelLeftToRightEdit.parameters = {
    testOptions: { waitForSelector: ['[data-attr=funnel-steps-bar-chart] canvas[role="img"]', '.PayGateMini'] },
}

// Steps viz with "Compare to previous" on: each step renders a current and a (desaturated) previous
// bar. The funnels-compare flag gates the toggle — without it the compare data degrades to a single
// bar per step and the snapshot is wrong.
export const FunnelLeftToRightCompare: Story = createInsightStory(__funnelLeftToRightCompare as any)
FunnelLeftToRightCompare.parameters = {
    featureFlags: [FEATURE_FLAGS.PRODUCT_ANALYTICS_FUNNELS_COMPARE],
    testOptions: { waitForSelector: ['[data-attr=funnel-steps-bar-chart] canvas[role="img"]', '.PayGateMini'] },
}
FunnelLeftToRightCompare.play = waitForFunnelToStabilize

export const FunnelLeftToRightBreakdown: Story = createInsightStory(__funnelLeftToRightBreakdown as any)
FunnelLeftToRightBreakdown.parameters = {
    testOptions: {
        waitForSelector: ['[data-attr=funnel-steps-bar-chart] canvas[role="img"]', '.PayGateMini'],
        snapshotBrowsers: [],
    },
}
export const FunnelLeftToRightBreakdownEdit: Story = createInsightStory(__funnelLeftToRightBreakdown as any, 'edit')
FunnelLeftToRightBreakdownEdit.parameters = {
    testOptions: { waitForSelector: ['[data-attr=funnel-steps-bar-chart] canvas[role="img"]', '.PayGateMini'] },
}
FunnelLeftToRightBreakdownEdit.play = waitForFunnelToStabilize
export const FunnelTopToBottom: Story = createInsightStory(__funnelTopToBottom as any)
FunnelTopToBottom.parameters = {
    testOptions: { waitForSelector: ['[data-attr=funnel-bar-horizontal] canvas[role="img"]'] },
}
export const FunnelTopToBottomEdit: Story = createInsightStory(__funnelTopToBottom as any, 'edit')
FunnelTopToBottomEdit.parameters = {
    testOptions: { waitForSelector: ['[data-attr=funnel-bar-horizontal] canvas[role="img"]'] },
}
export const FunnelTopToBottomBreakdown: Story = createInsightStory(__funnelTopToBottomBreakdown as any)
FunnelTopToBottomBreakdown.parameters = {
    testOptions: { waitForSelector: ['[data-attr=funnel-bar-horizontal] canvas[role="img"]'] },
}
export const FunnelTopToBottomBreakdownEdit: Story = createInsightStory(__funnelTopToBottomBreakdown as any, 'edit')
FunnelTopToBottomBreakdownEdit.parameters = {
    testOptions: { waitForSelector: ['[data-attr=funnel-bar-horizontal] canvas[role="img"]'] },
}
export const FunnelHistoricalTrends: Story = createInsightStory(__funnelHistoricalTrends as any)
FunnelHistoricalTrends.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph-funnel] > canvas' },
}
export const FunnelHistoricalTrendsEdit: Story = createInsightStory(__funnelHistoricalTrends as any, 'edit')
FunnelHistoricalTrendsEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph-funnel] > canvas' },
}
export const FunnelHistoricalTrendsCompare: Story = createInsightStory(__funnelHistoricalTrendsCompare as any)
FunnelHistoricalTrendsCompare.parameters = {
    // funnels-compare gates the Compare-to-previous toggle on funnel trends — without this the
    // dual-period chart degrades back to the single-period rendering and the snapshot is wrong.
    featureFlags: [FEATURE_FLAGS.PRODUCT_ANALYTICS_FUNNELS_COMPARE],
    testOptions: { waitForSelector: '[data-attr=trend-line-graph-funnel] > canvas' },
}

export const FunnelTimeToConvert: Story = createInsightStory(__funnelTimeToConvert as any)
FunnelTimeToConvert.parameters = { testOptions: { waitForSelector: '[data-attr=funnel-histogram] canvas[role="img"]' } }
export const FunnelTimeToConvertEdit: Story = createInsightStory(__funnelTimeToConvert as any, 'edit')
FunnelTimeToConvertEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=funnel-histogram] canvas[role="img"]' },
}

export const FunnelWithInlineEventsEdit: Story = createInsightStory(__funnelLeftToRightWithInlineEvents as any, 'edit')
FunnelWithInlineEventsEdit.parameters = {
    testOptions: { waitForSelector: ['[data-attr=funnel-steps-bar-chart] canvas[role="img"]', '.PayGateMini'] },
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

export const FunnelLeftToRightEditViewports: Story = createInsightStory(__funnelLeftToRight as any, 'edit')
FunnelLeftToRightEditViewports.parameters = {
    testOptions: {
        waitForSelector: ['[data-attr=funnel-steps-bar-chart] canvas[role="img"]', '.PayGateMini'],
        viewportWidths: ['medium', 'wide', 'superwide'],
    },
}
FunnelLeftToRightEditViewports.play = waitForFunnelToStabilize

/* eslint-enable @typescript-eslint/no-var-requires */
