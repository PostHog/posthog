import { render, screen } from '@testing-library/react'

import { ExperimentMetric, ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { ChartEmptyState } from './ChartEmptyState'

const metric = {
    kind: NodeKind.ExperimentMetric,
    metric_type: ExperimentMetricType.MEAN,
    uuid: 'metric-mean',
    source: { kind: NodeKind.EventsNode, event: 'purchase' },
} as unknown as ExperimentMetric

describe('ChartEmptyState', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('waits for the experiment to start before it has any results', () => {
        render(<ChartEmptyState height={200} experimentStarted={false} metric={metric} />)
        expect(screen.queryByText(/Waiting for experiment to start/)).not.toBeNull()
    })

    it('shows a neutral waiting state, not a red error, when the baseline has no exposures yet', () => {
        // The first minutes of every experiment: split_baseline_and_test_variants raises no_data.
        render(
            <ChartEmptyState
                height={200}
                experimentStarted={true}
                metric={metric}
                error={{ code: 'no_data', detail: "No exposures for the 'control' variant yet." }}
            />
        )
        expect(screen.queryByText(/Waiting for exposures/)).not.toBeNull()
        expect(screen.queryByText(/Error loading metric results/)).toBeNull()
    })

    it('still shows the error state for a real failure', () => {
        render(
            <ChartEmptyState
                height={200}
                experimentStarted={true}
                metric={metric}
                error={{ code: 'server_error', detail: 'Something broke' }}
            />
        )
        expect(screen.queryByText(/Error loading metric results/)).not.toBeNull()
    })
})
