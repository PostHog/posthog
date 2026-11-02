import { AccessControlResourceType } from '~/types'

import { resourceLabel, resourceTypeToString } from './accessControlUtils'

describe('accessControlUtils', () => {
    test.each([
        [AccessControlResourceType.FeatureFlag, 'Feature flags', 'feature flag'],
        [AccessControlResourceType.McpAnalytics, 'MCP analytics', 'MCP analytic'],
        [AccessControlResourceType.MarketingAnalytics, 'Marketing analytics', 'marketing analytics resource'],
    ])('names %s as "%s" in lists and "%s" in messages', (resource, label, singular) => {
        expect(resourceLabel(resource)).toEqual(label)
        expect(resourceTypeToString(resource)).toEqual(singular)
    })
})
