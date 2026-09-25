import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import {
    ExperimentMetric,
    ExperimentMetricType,
    NewExperimentQueryResponse,
    NodeKind,
} from '~/queries/schema/schema-general'

import { CUPED_ADJUSTED_EXPLANATION } from 'products/experiments/frontend/components/CupedAdjustedTag'

import { NotebookCompactTable } from './NotebookCompactTable'

jest.mock('~/scenes/experiments/ExperimentView/VariantTag', () => ({
    VariantTag: ({ variantKey }: { variantKey: string }) => <span>{variantKey}</span>,
}))

const metric: ExperimentMetric = {
    kind: NodeKind.ExperimentMetric,
    metric_type: ExperimentMetricType.MEAN,
    source: { kind: NodeKind.EventsNode, event: 'purchase' },
} as ExperimentMetric

const result = {
    baseline: {
        key: 'control',
        method: 'bayesian',
        sum: 100,
        number_of_samples: 1000,
        credible_interval: [0, 0],
    },
    variant_results: [
        {
            key: 'test',
            method: 'bayesian',
            sum: 90,
            number_of_samples: 1000,
            credible_interval: [0.01, 0.05],
            delta: 0.03,
            cuped_adjusted: true,
            chance_to_win: 0.8,
        },
    ],
} as unknown as NewExperimentQueryResponse

describe('NotebookCompactTable', () => {
    it('explains a CUPED-adjusted delta on hover', async () => {
        const user = userEvent.setup()
        render(<NotebookCompactTable result={result} metric={metric} />)

        expect(screen.queryByText(CUPED_ADJUSTED_EXPLANATION)).toBeNull()

        await user.hover(screen.getByText('CUPED'))

        expect(await screen.findByText(CUPED_ADJUSTED_EXPLANATION)).toBeTruthy()
    })
})
