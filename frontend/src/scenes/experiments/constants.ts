import {
    AccessControlLevel,
    BaseMathType,
    ExperimentConclusion,
    GroupMathType,
    HogQLMathType,
    PropertyMathType,
} from '~/types'
import type { Experiment } from '~/types'

export enum MetricInsightId {
    Trends = 'new-experiment-trends-metric',
    TrendsExposure = 'new-experiment-trends-exposure',
    Funnels = 'new-experiment-funnels-metric',
    SecondaryTrends = 'new-experiment-secondary-trends',
    SecondaryFunnels = 'new-experiment-secondary-funnels',
}

export const LEGACY_EXPERIMENT_ALLOWED_MATH_TYPES = [
    BaseMathType.TotalCount,
    BaseMathType.UniqueUsers,
    BaseMathType.UniqueSessions,
    BaseMathType.WeeklyActiveUsers,
    BaseMathType.MonthlyActiveUsers,
    BaseMathType.FirstTimeForUser,
    GroupMathType.UniqueGroup,
    PropertyMathType.Sum,
    HogQLMathType.HogQL,
] as const

export const EXPERIMENT_VARIANT_MULTIPLE = '$multiple'

export const EXPERIMENT_MIN_EXPOSURES_FOR_RESULTS = 50
export const EXPERIMENT_MIN_METRIC_VALUE_FOR_RESULTS = 10
export const CONCLUSION_DISPLAY_CONFIG: Record<
    ExperimentConclusion,
    { title: string; description: string; color: string }
> = {
    [ExperimentConclusion.Won]: {
        title: 'Won',
        description: 'The test variant(s) outperformed the control with statistical significance.',
        color: 'bg-success',
    },
    [ExperimentConclusion.Lost]: {
        title: 'Lost',
        description: 'The test variant(s) underperformed compared to the control with statistical significance.',
        color: 'bg-danger',
    },
    [ExperimentConclusion.Inconclusive]: {
        title: 'Inconclusive',
        description: 'No significant difference was detected between the variant(s) and the control.',
        color: 'bg-warning',
    },
    [ExperimentConclusion.StoppedEarly]: {
        title: 'Stopped Early',
        description: 'The experiment was terminated before reaching a conclusive result.',
        color: 'bg-muted-alt',
    },
    [ExperimentConclusion.Invalid]: {
        title: 'Invalid',
        description:
            'The experiment data is unreliable due to issues like tracking errors, incorrect setup, or external disruptions.',
        color: 'bg-muted-alt',
    },
}

export const NEW_EXPERIMENT: Experiment = {
    id: 'new',
    name: '',
    description: '',
    type: 'product',
    feature_flag_key: '',
    filters: {},
    metrics: [] as any[],
    metrics_secondary: [] as any[],
    secondary_metrics: [] as any[],
    primary_metrics_ordered_uuids: null,
    secondary_metrics_ordered_uuids: null,
    saved_metrics_ids: [] as any[],
    saved_metrics: [] as any[],
    parameters: {
        feature_flag_variants: [
            { key: 'control', rollout_percentage: 50 },
            { key: 'test', rollout_percentage: 50 },
        ] as any[],
    },
    created_at: null,
    created_by: null,
    updated_at: null,
    holdout_id: null,
    exposure_criteria: {
        filterTestAccounts: true,
    },
    user_access_level: AccessControlLevel.Member,
}
