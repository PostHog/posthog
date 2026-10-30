import { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'

/** One aggregated count per series, the shape a bold-number trends query returns. */
function counts(...values: number[]): { results: { aggregated_value: number }[] } {
    return { results: values.map((value) => ({ aggregated_value: value })) }
}

function scene(matchingGenerations: number): ReturnType<typeof mswDecorator> {
    return mswDecorator({
        get: {
            '/api/projects/:team_id/evaluations/': toPaginatedResponse([]),
            '/api/projects/:team_id/evaluation_directories/': [],
            '/api/environments/:team_id/llm_analytics/provider_keys/': toPaginatedResponse([]),
            '/api/projects/:team_id/llm_analytics/provider_keys/': toPaginatedResponse([]),
            '/api/environments/:team_id/llm_analytics/evaluation_config/': { active_provider_key: null },
        },
        // The query client puts the query kind in the path.
        post: {
            '/api/environments/:team_id/query/:kind/': counts(matchingGenerations, Math.round(matchingGenerations / 3)),
            '/api/environments/:team_id/query/': counts(matchingGenerations, Math.round(matchingGenerations / 3)),
        },
    })
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/AI observability/New evaluation',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-10-20',
        pageUrl: urls.aiObservabilityEvaluation('new'),
        testOptions: {
            waitForSelector: '[data-attr="llma-evaluation-create-step-body-name"]',
        },
    },
}
export default meta
type Story = StoryObj<{}>

export const FromScratch: Story = { decorators: [scene(1240)] }

export const FromTemplate: Story = {
    parameters: { pageUrl: `${urls.aiObservabilityEvaluation('new')}?template=helpfulness` },
    decorators: [scene(1240)],
}

/** Clicks one part of the sentence, the way someone does, and waits for the step it opens. */
async function openPart(canvasElement: HTMLElement, part: string, panelText: string): Promise<void> {
    const button = await waitFor(() => {
        const element = canvasElement.querySelector<HTMLElement>(`[data-attr="llma-evaluation-create-part-${part}"]`)
        if (!element) {
            throw new Error(`Waiting for the ${part} part`)
        }
        return element
    })
    button.click()
    await within(canvasElement).findByText(panelText)
}

export const ReportsOpen: Story = {
    parameters: {
        pageUrl: `${urls.aiObservabilityEvaluation('new')}?template=helpfulness`,
        testOptions: { waitForSelector: '[data-attr="llma-evaluation-create-step-body-reports"]' },
    },
    decorators: [scene(1240)],
    play: async ({ canvasElement }) => {
        await openPart(canvasElement, 'reports', 'Send a report')
    },
}

export const SentimentEvaluation: Story = {
    parameters: { testOptions: { waitForSelector: '[data-attr="llma-evaluation-create-step-body-check"]' } },
    decorators: [scene(1240)],
    play: async ({ canvasElement }) => {
        await openPart(canvasElement, 'method', 'Sentiment')
        within(canvasElement).getByText('Sentiment').click()
        await within(canvasElement).findByText('a sentiment classifier')
    },
}

/** The "What it runs on" step, with the warning shown when no generation matched. */
export const NothingMatches: Story = {
    parameters: {
        pageUrl: `${urls.aiObservabilityEvaluation('new')}?template=helpfulness`,
        testOptions: { waitForSelector: '[data-attr="llma-evaluation-create-volume-none"]' },
    },
    decorators: [scene(0)],
    play: async ({ canvasElement }) => {
        await openPart(canvasElement, 'triggers', 'Triggers')
        await waitFor(() => {
            if (!canvasElement.querySelector('[data-attr="llma-evaluation-create-volume-none"]')) {
                throw new Error('Waiting for the volume estimate')
            }
        })
    },
}
