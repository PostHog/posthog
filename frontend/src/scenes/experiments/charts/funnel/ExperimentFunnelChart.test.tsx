import '@testing-library/jest-dom'

import { cleanup, render, waitFor } from '@testing-library/react'

import { setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import EXPERIMENT_WITH_FUNNEL_METRIC from '~/mocks/fixtures/api/experiments/experiment_with_funnel_metric.json'
import MULTI_STEP_RESULT from '~/mocks/fixtures/api/experiments/funnel_metric_result_multi_step.json'
import { ExperimentFunnelMetric, NewExperimentQueryResponse } from '~/queries/schema/schema-general'
import { Experiment } from '~/types'

import { ExperimentFunnelChart } from './ExperimentFunnelChart'

let cleanupJsdom: () => void
let cleanupRaf: () => void

describe('ExperimentFunnelChart', () => {
    beforeEach(() => {
        cleanupJsdom = setupJsdom()
        cleanupRaf = setupSyncRaf()
    })

    afterEach(() => {
        cleanupRaf()
        cleanupJsdom()
        cleanup()
    })

    it('draws no band past the metric series, so no click can ask for a step the backend refuses', async () => {
        // A three-step result rendered against a one-step metric: what someone sees after they edit
        // the metric down while an older result is still on screen.
        render(
            <ExperimentFunnelChart
                result={MULTI_STEP_RESULT as unknown as NewExperimentQueryResponse}
                experiment={EXPERIMENT_WITH_FUNNEL_METRIC as unknown as Experiment}
                metric={EXPERIMENT_WITH_FUNNEL_METRIC.metrics[0] as ExperimentFunnelMetric}
            />
        )

        await waitFor(() => {
            expect(document.querySelectorAll('[data-attr="hog-funnel-step-footer-cell"]')).toHaveLength(2)
        })
    })
})
