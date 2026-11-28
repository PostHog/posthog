import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'

import { mswDecorator } from '~/mocks/browser'

import type { OfflineExperimentReadApi } from '../generated/api.schemas'
import { comparisonUrl } from './offlineComparison'
import { OfflineExperimentComparison } from './OfflineExperimentComparison'
import { overviewHistory, overviewScorers } from './offlineOverviewFixtures'

const points = overviewHistory(overviewScorers[0]).slice(0, 3)
const experiments: OfflineExperimentReadApi[] = points.map(({ experiment }, index) => {
    const value = [0.8412, 0.8449, 0.78][index]
    return {
        ...experiment,
        name: ['Support replies · production', 'Support replies · revised prompt', 'Support replies · compact model'][
            index
        ],
        experiment_score: {
            definition_id: '90000000-0000-4000-8000-000000000001',
            scorer_version_id: '90000000-0000-4000-8000-000000000002',
            name: 'Release quality',
            version: 1,
            kind: 'numeric',
            config: { passing_rule: { operator: 'gte', threshold: 0.8 } },
            status: 'ok',
            value,
            passed: value >= 0.8,
            inputs: [],
        },
    }
})
const experimentIds = experiments.map(({ id }) => id)
const detailPath = '/api/projects/:team/ai_observability/offline_experiments/:id/'

const meta: Meta<typeof OfflineExperimentComparison> = {
    title: 'Scenes-App/AI observability/Offline experiments/Comparison',
    component: OfflineExperimentComparison,
    args: { teamId: 997, experimentIds, canOpenDatasets: true },
    parameters: { pageUrl: comparisonUrl(experimentIds, {}), mockDate: '2026-09-28T12:00:00Z' },
    decorators: [
        mswDecorator({
            get: {
                [detailPath]: ({ params }) => experiments.find((experiment) => experiment.id === params.id),
                [detailPath + 'scorer_summaries/']: ({ params }) => ({
                    results: [points.find(({ experiment }) => experiment.id === params.id)!.summary],
                    count: 1,
                    next_cursor: null,
                }),
            },
        }),
    ],
}
export default meta
type Story = StoryObj<typeof meta>

export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-[520px]">
                <Story />
            </div>
        ),
    ],
    play: async ({ canvasElement }) => {
        await within(canvasElement).findByText('0.8449')
    },
}

export const PartialFailure: Story = {
    decorators: [
        mswDecorator({
            get: {
                [`/api/projects/:team/ai_observability/offline_experiments/${experimentIds[0]}/scorer_summaries/`]: [
                    503,
                    { detail: 'Request timed out' },
                ],
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        await within(canvasElement).findByRole('button', { name: 'Retry failed runs' })
        await within(canvasElement).findByRole('table')
    },
}
