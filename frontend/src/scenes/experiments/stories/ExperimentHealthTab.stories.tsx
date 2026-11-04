import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { makeDelay } from 'lib/utils/async'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_WITH_MEAN_METRIC from '~/mocks/fixtures/api/experiments/experiment_with_mean_metric.json'
import EXPOSURE_QUERY_RESULT from '~/mocks/fixtures/api/experiments/exposure_query_result.json'
import MEAN_METRIC_RESULT from '~/mocks/fixtures/api/experiments/mean_metric_result.json'
import { NodeKind } from '~/queries/schema/schema-general'

import { recalculationMocks, resultsByMetricType } from './recalculationMocks'

type Check = { key: string; name: string; status: string; reason: string | null }

const passed = (key: string, name: string): Check => ({ key, name, status: 'passed', reason: null })

const EXPERIMENT_CHECKS: Check[] = [
    passed('flag_state', "Flag state that doesn't match the experiment"),
    passed('flag_history', 'Unreadable flag history'),
    passed('split_changed_mid_run', 'Variant split changes since launch'),
    passed('bucketing_changed_mid_run', 'Variant assignment changes since launch'),
    passed('release_conditions_changed_mid_run', 'Release condition changes since launch'),
    passed('flag_variants_mismatch', 'Flag variants not set up'),
    passed('forced_variant_release_condition', 'Release conditions that force a variant'),
    {
        key: 'new_flag_no_traffic',
        name: 'Flag calls not received yet',
        status: 'not_applicable',
        reason: 'Runs before launch',
    },
    passed('no_metric', 'Metrics not set up'),
    passed('metric_event_not_ingested', 'Metric events not received yet'),
    passed('metric_cannot_compile', 'Invalid metric definitions'),
    passed('metric_calculation_failed', 'Failed metric calculations'),
    passed('metric_all_zero', 'Metrics at zero in every variant'),
    passed('exposure_criteria_cannot_match', "Exposure criteria that can't match"),
    passed('exposure_filters', 'Dynamic cohorts in the exposure criteria'),
    passed('early_significance', 'Significance on a small sample'),
    passed('metrics_not_matured', 'Metric windows not complete yet'),
]

const EXPOSURE_CHECKS: Check[] = [
    passed('zero_exposures', 'Exposures not received since launch'),
    passed('test_account_filter_removes_exposures', 'Test account filters that leave out most users'),
    passed('srm', 'Split of users across variants'),
    {
        key: 'bias_risk_multiple_excluded',
        name: 'Bias from an uneven split',
        status: 'not_applicable',
        reason: 'The split is even',
    },
    passed('multiple_variants_share', 'Users exposed to multiple variants'),
]

const withStatus = (checks: Check[], key: string, status: string): Check[] =>
    checks.map((check) => (check.key === key ? { ...check, status } : check))

const HEALTHY_EXPOSURES = {
    ...EXPOSURE_QUERY_RESULT,
    total_exposures: { control: 1012, 'test-1': 993, 'test-2': 995, $multiple: 18 },
    sample_ratio_mismatch: { expected: { control: 1020, 'test-1': 990, 'test-2': 990 }, p_value: 0.62 },
    health_findings: [],
    health_checks: EXPOSURE_CHECKS,
}

const EXPOSURES_WITH_SRM = {
    ...EXPOSURE_QUERY_RESULT,
    sample_ratio_mismatch: { expected: { control: 1020, 'test-1': 990, 'test-2': 990 }, p_value: 0.00004 },
    health_findings: [
        {
            code: 'srm',
            subcode: null,
            reason: null,
            severity: 'warning',
            title: 'Users are not split across variants as configured',
            detail: "The distribution of users across variants doesn't match your configured rollout percentages (p < 0.001). This may indicate issues with randomization or data collection.",
            evidence: { p_value: 0.00004 },
            actions: [],
            diagnostic_ref: 'A2',
        },
    ],
    health_checks: withStatus(EXPOSURE_CHECKS, 'srm', 'finding'),
}

const METRIC_NOTE = {
    code: 'metrics_not_matured',
    subcode: null,
    reason: null,
    severity: 'info',
    title: 'Some users are still inside the conversion window',
    detail: 'The primary metric counts conversions up to 7 days after exposure. Users exposed in the last 7 days can still convert, so the results can still change.',
    evidence: {},
    actions: [],
    diagnostic_ref: null,
}

const RECALCULATION = recalculationMocks(
    EXPERIMENT_WITH_MEAN_METRIC,
    resultsByMetricType(EXPERIMENT_WITH_MEAN_METRIC, { mean: MEAN_METRIC_RESULT })
)

function healthMocks(health: object, exposures: object): Parameters<typeof mswDecorator>[0] {
    return {
        get: {
            ...RECALCULATION.get,
            [`/api/projects/:team_id/experiments/${EXPERIMENT_WITH_MEAN_METRIC.id}/`]: EXPERIMENT_WITH_MEAN_METRIC,
            [`/api/projects/:team_id/experiments/${EXPERIMENT_WITH_MEAN_METRIC.id}/health/`]: health,
            [`/api/projects/:team_id/experiment_holdouts`]: [],
            [`/api/projects/:team_id/experiment_saved_metrics/`]: [],
            [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_MEAN_METRIC.feature_flag.id}/`]: {},
            [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_MEAN_METRIC.feature_flag.id}/status/`]: {},
            [`/api/environments/:team_id/default_release_conditions/`]: [],
        },
        post: {
            ...RECALCULATION.post,
            '/api/environments/:team_id/query/:kind': async ({ request }) => {
                const body = (await request.json()) as Record<string, any>
                return body.query.kind === NodeKind.ExperimentExposureQuery ? [200, exposures] : [404]
            },
        },
    }
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Experiments/Health tab',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-01-27',
        pageUrl: `${urls.experiment(EXPERIMENT_WITH_MEAN_METRIC.id)}?tab=health`,
        featureFlags: [FEATURE_FLAGS.EXPERIMENT_HEALTH_FINDINGS],
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj<{}>

export const AllChecksPassed: Story = {
    decorators: [
        mswDecorator(
            healthMocks(
                { findings: [METRIC_NOTE], checks: withStatus(EXPERIMENT_CHECKS, 'metrics_not_matured', 'finding') },
                HEALTHY_EXPOSURES
            )
        ),
    ],
    play: async () => {
        await makeDelay(1500)()
    },
}

export const WithAnIssue: Story = {
    decorators: [mswDecorator(healthMocks({ findings: [], checks: EXPERIMENT_CHECKS }, EXPOSURES_WITH_SRM))],
    play: async () => {
        await makeDelay(1500)()
    },
}
