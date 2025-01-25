import { BaseMathType, GroupMathType, HogQLMathType, PropertyMathType } from '~/types'

export enum MetricInsightId {
    Trends = 'new-experiment-trends-metric',
    TrendsExposure = 'new-experiment-trends-exposure',
    Funnels = 'new-experiment-funnels-metric',
    SecondaryTrends = 'new-experiment-secondary-trends',
    SecondaryFunnels = 'new-experiment-secondary-funnels',
}

export const EXPERIMENT_ALLOWED_MATH_TYPES = [
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
