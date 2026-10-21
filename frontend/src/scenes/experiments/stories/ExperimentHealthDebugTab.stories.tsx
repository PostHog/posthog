import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_WITH_MEAN_METRIC from '~/mocks/fixtures/api/experiments/experiment_with_mean_metric.json'
import EXPOSURE_QUERY_RESULT from '~/mocks/fixtures/api/experiments/exposure_query_result.json'
import MEAN_METRIC_RESULT from '~/mocks/fixtures/api/experiments/mean_metric_result.json'
import { NodeKind } from '~/queries/schema/schema-general'

import type { ExperimentHealthInputsApi } from 'products/experiments/frontend/generated/api.schemas'

import { recalculationMocks, resultsByMetricType } from './recalculationMocks'

const SPLIT_AFTER = [
    { key: 'control', rollout_percentage: 34 },
    { key: 'test-1', rollout_percentage: 33 },
    { key: 'test-2', rollout_percentage: 33 },
]

const EXPERIMENT_HEALTH = {
    findings: [
        {
            code: 'split_changed_mid_run',
            subcode: 'rebalanced',
            severity: 'warning',
            title: 'The variant split changed after launch',
            detail: '',
            evidence: {
                change_count: 1,
                from: 'January 20, 2025',
                to: 'January 20, 2025',
                exposed_before_change: true,
            },
            actions: ['open_feature_flag'],
            diagnostic_ref: 'E3',
        },
    ],
    checks: [
        { key: 'split_changed_mid_run', name: 'Variant split changes since launch', status: 'finding', reason: null },
        { key: 'flag_state', name: 'Feature flag rollout', status: 'passed', reason: null },
        { key: 'flag_history', name: 'Feature flag history', status: 'passed', reason: null },
        { key: 'no_metric', name: 'Metrics', status: 'passed', reason: null },
    ],
}

// Typed as the generated response, so a new required field on the serializer breaks the typecheck here.
const HEALTH_INPUTS: ExperimentHealthInputsApi = {
    is_launched: true,
    is_running: true,
    has_ended: false,
    is_paused: false,
    archived: false,
    baseline_variant_key: null,
    excluded_variant_keys: [],
    primary_metric_count: 1,
    secondary_metric_count: 0,
    flag: {
        active: true,
        deleted: false,
        release_conditions: [
            { number: 1, rollout_percentage: 100, property_count: 1, reachable: true, pinned_variant: 'test-1' },
            { number: 2, rollout_percentage: 100, property_count: 0, reachable: true, pinned_variant: null },
        ],
        variants: SPLIT_AFTER,
        split_text: 'control 34%, test-1 33%, test-2 33%',
    },
    flag_history: {
        checked: true,
        not_checked_reason: null,
        launched_at: '2025-01-06T10:00:00Z',
        team_timezone: 'UTC',
        changes: [
            {
                kind: 'split',
                changed_at: '2025-01-20T14:30:00Z',
                changed: 'Split',
                before: 'control 50%, test-1 25%, test-2 25%',
                after: 'control 34%, test-1 33%, test-2 33%',
                counted: true,
            },
        ],
        exposed_before_first: true,
        exposed_between: [
            { kind: 'split', question: 'Exposed between the first and last split change', exposed: null },
        ],
    },
    condition_set_traffic_status: 'read',
    condition_set_traffic: {
        since: '2025-01-20T14:30:00Z',
        team_timezone: 'UTC',
        people_by_set: [
            { condition_set: 1, people: 12 },
            { condition_set: 2, people: 2988 },
        ],
        calls: 4200,
        remotely_evaluated_calls: 4116,
        people_assigned_outside: 0,
    },
    reader_access: { can_read_flag_history: true, can_query_events: true, denied_event_properties: [] },
    exposures: {
        status: 'ready',
        computed_at: '2025-01-27T06:00:00Z',
        totals: {
            total_exposures: { control: 989, 'test-1': 874, 'test-2': 1137 },
            multiple_variant_handling: 'exclude',
            sample_ratio_mismatch_p_value: 0.31,
            hours_since_launch: 500,
        },
        findings: [],
        error: null,
    },
    project: {
        team_defaults: { status: 'skipped', data: null },
        sdk_profile: { status: 'skipped', data: null },
    },
}

const RECALCULATION = recalculationMocks(
    EXPERIMENT_WITH_MEAN_METRIC,
    resultsByMetricType(EXPERIMENT_WITH_MEAN_METRIC, { mean: MEAN_METRIC_RESULT })
)

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Experiments',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-01-27',
        pageUrl: `${urls.experiment(EXPERIMENT_WITH_MEAN_METRIC.id)}?tab=health-debug`,
        featureFlags: [FEATURE_FLAGS.EXPERIMENT_HEALTH_FINDINGS],
    },
    decorators: [
        mswDecorator({
            get: {
                ...RECALCULATION.get,
                [`/api/projects/:team_id/experiments/${EXPERIMENT_WITH_MEAN_METRIC.id}/`]: EXPERIMENT_WITH_MEAN_METRIC,
                [`/api/projects/:team_id/experiments/${EXPERIMENT_WITH_MEAN_METRIC.id}/health/`]: EXPERIMENT_HEALTH,
                [`/api/projects/:team_id/experiments/${EXPERIMENT_WITH_MEAN_METRIC.id}/health_inputs/`]: HEALTH_INPUTS,
                [`/api/projects/:team_id/experiment_holdouts`]: [],
                [`/api/projects/:team_id/experiment_saved_metrics/`]: [],
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_MEAN_METRIC.feature_flag.id}/`]: {},
                [`/api/projects/:team_id/feature_flags/${EXPERIMENT_WITH_MEAN_METRIC.feature_flag.id}/status/`]: {},
                [`/api/environments/:team_id/default_release_conditions/`]: [],
            },
            post: {
                ...RECALCULATION.post,
                // Exposures still load through experimentLogic; metric results come from the recalculation run.
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    return body.query.kind === NodeKind.ExperimentExposureQuery ? [200, EXPOSURE_QUERY_RESULT] : [404]
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

// Staff only: the tab shows for staff with the health findings flag, so superpowers come from the debug preflight.
export const ExperimentHealthDebugTab: Story = {}
