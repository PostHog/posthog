import { ConversionGoalFilter } from '~/queries/schema/schema-general'
import { PropertyMathType } from '~/types'

// Mirrors `_revenue_goal_error` on the write path. The flag on its own changes nothing: the query
// only sums when math is a sum type, and sums nothing without a property, so a goal flagged here
// would feed ROAS a conversion count or a row of zeros.
export const revenueDisabledReason = (goal: ConversionGoalFilter): string | undefined => {
    if (goal.math !== PropertyMathType.Sum) {
        return 'Set this goal\'s math to "Sum" first, so the amount is totalled rather than counted.'
    }
    if (!goal.math_property) {
        return 'Choose the property holding the amount first.'
    }
    return undefined
}

// Changing math can invalidate a flag that was legal when it was set.
export const withValidFlags = (goal: ConversionGoalFilter): ConversionGoalFilter =>
    revenueDisabledReason(goal) ? { ...goal, counts_as_revenue: false } : goal
