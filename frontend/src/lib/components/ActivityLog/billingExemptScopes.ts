import { ActivityScope } from '~/types'

/**
 * Scopes whose history belongs to their own product rather than to the paid activity log, so the
 * paywall doesn't apply to them.
 * Keep in sync with BILLING_EXEMPT_SCOPES in posthog/api/advanced_activity_logs/constants.py
 */
export const BILLING_EXEMPT_ACTIVITY_SCOPES: Set<ActivityScope> = new Set([
    ActivityScope.FEATURE_FLAG,
    ActivityScope.EXPERIMENT,
])

/** Whether an activity log limited to these scopes can skip the billing gate. */
export const isActivityScopeBillingExempt = (
    scope: ActivityScope | ActivityScope[] | string | null | undefined
): boolean => {
    const scopes = scope == null ? [] : Array.isArray(scope) ? scope : [scope]
    return scopes.length > 0 && scopes.every((s) => BILLING_EXEMPT_ACTIVITY_SCOPES.has(s as ActivityScope))
}
