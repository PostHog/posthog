import { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { SampleDataState, SampleDataVariant } from './SampleDataState'

const VARIANTS: SampleDataVariant[] = ['line', 'bar', 'pie', 'funnel', 'number', 'table']

const meta: Meta<typeof SampleDataState> = {
    component: SampleDataState,
    title: 'Components/Sample Data State',
    parameters: {
        testOptions: {
            waitForSelector: '[data-attr="insight-sample-data-state"]',
            waitForLoadersToDisappear: false,
        },
    },
}
export default meta
type Story = StoryObj<typeof SampleDataState>

export const AllVariants: Story = {
    render: () => (
        <div className="grid grid-cols-3 gap-4">
            {VARIANTS.map((variant) => (
                <div key={variant} className="h-60 border rounded flex flex-col">
                    <div className="p-2 text-xs text-tertiary">{variant}</div>
                    <SampleDataState variant={variant} />
                </div>
            ))}
        </div>
    ),
}

/**
 * The real insight-detail page doesn't wrap the chart in a fixed-height div like the stories above -
 * it renders inside `.InsightVizDisplay > .TrendsInsight`, which derives its height from a CSS custom
 * property rather than a fixed one. A fixed-height wrapper (like `AllVariants` uses) hands
 * `.SampleDataState` a definite height either way, so it can't catch a regression in how `__chart`
 * fills that height. This story reuses the real container classes instead.
 */
export const InTrendsInsightContainer: Story = {
    // Loaded here rather than at module scope so only this story pays for and applies
    // InsightVizDisplay's page-level styles, not every other story in this file.
    loaders: [async () => void (await import('~/queries/nodes/InsightViz/InsightViz.scss'))],
    render: () => (
        <div className="InsightVizDisplay border rounded w-160">
            <div className="TrendsInsight TrendsInsight--ActionsLineGraph">
                <SampleDataState variant="line" />
            </div>
        </div>
    ),
}

/** The wizard's cloud run is still working - no PR yet, so an "Installing PostHog..." tag shows. */
export const WizardInstalling: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/tasks/': () => [
                    200,
                    {
                        count: 1,
                        results: [
                            {
                                id: 'sample-task-id',
                                created_at: '2026-07-01T00:00:00Z',
                                latest_run: {
                                    created_at: '2026-07-01T00:10:00Z',
                                    status: 'in_progress',
                                    output: null,
                                },
                            },
                        ],
                    },
                ],
            },
        }),
    ],
    render: () => (
        <div className="h-60 w-160 border rounded flex flex-col">
            <SampleDataState variant="line" />
        </div>
    ),
}

/** Hover the "Sample data" tag to see the tooltip point at the unmerged onboarding-wizard PR. */
export const WithSetupPullRequest: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/tasks/': () => [
                    200,
                    {
                        count: 1,
                        results: [
                            {
                                id: 'sample-task-id',
                                created_at: '2026-07-01T00:00:00Z',
                                latest_run: {
                                    created_at: '2026-07-01T00:10:00Z',
                                    output: {
                                        pr_url: 'https://github.com/posthog/posthog/pull/12345',
                                        pr_merged: false,
                                    },
                                },
                            },
                        ],
                    },
                ],
            },
        }),
    ],
    render: () => (
        <div className="h-60 w-160 border rounded flex flex-col">
            <SampleDataState variant="line" />
        </div>
    ),
}
