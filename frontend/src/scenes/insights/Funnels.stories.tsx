import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { mswDecorator } from '~/mocks/browser'

import __funnelHistoricalTrends from '../../mocks/fixtures/api/projects/team_id/insights/funnelHistoricalTrends.json'
import __funnelLeftToRight from '../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRight.json'
import __funnelLeftToRightWithInlineEvents from '../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRightWithInlineEvents.json'
import __funnelTimeToConvert from '../../mocks/fixtures/api/projects/team_id/insights/funnelTimeToConvert.json'

// These stories cover the insight scene in edit mode, one per funnel viz sub-type, since each
// sub-type has its own editor controls. Chart rendering itself is covered by the component-level
// stories in products/product_analytics/frontend/insights/funnels/.
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

export const FunnelLeftToRightEdit: Story = createInsightStory(__funnelLeftToRight as any, 'edit')
FunnelLeftToRightEdit.parameters = {
    testOptions: { waitForSelector: ['[data-attr=funnel-steps-bar-chart] canvas[role="img"]', '.PayGateMini'] },
}

export const FunnelHistoricalTrendsEdit: Story = createInsightStory(__funnelHistoricalTrends as any, 'edit')
FunnelHistoricalTrendsEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph-funnel] > canvas' },
}

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
