import { isActivityScopeBillingExempt } from 'lib/components/ActivityLog/billingExemptScopes'

import { ActivityScope } from '~/types'

describe('billing exempt activity scopes', () => {
    test.each([
        [ActivityScope.FEATURE_FLAG, true],
        [ActivityScope.EXPERIMENT, true],
        [ActivityScope.INSIGHT, false],
        [[ActivityScope.FEATURE_FLAG, ActivityScope.EXPERIMENT], true],
        [[ActivityScope.FEATURE_FLAG, ActivityScope.INSIGHT], false],
        [[], false],
        [undefined, false],
    ])('%s is exempt: %s', (scope, expected) => {
        expect(isActivityScopeBillingExempt(scope)).toBe(expected)
    })
})
