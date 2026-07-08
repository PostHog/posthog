import { connect, kea, path, selectors } from 'kea'

import { superpowersLogic } from 'lib/components/Superpowers/superpowersLogic'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import { incidentStatusLogic } from './incidentStatusLogic'
import type { posthogStatusLogicType } from './posthogStatusLogicType'

export type PostHogStatusType = 'operational' | 'degraded_performance' | 'partial_outage' | 'major_outage'
export type PostHogStatusBadgeStatus = 'success' | 'warning' | 'danger'

export const posthogStatusLogic = kea<posthogStatusLogicType>([
    path(['lib', 'components', 'HelpMenu', 'posthogStatusLogic']),
    connect({
        values: [
            incidentStatusLogic,
            ['status', 'statusDescription', 'statusPageUrl'],
            superpowersLogic,
            ['fakeStatusOverride', 'superpowersEnabled'],
        ],
    }),
    selectors({
        postHogStatus: [(s) => [s.status], (status): PostHogStatusType => status],
        isFakeStatus: [
            (s) => [s.superpowersEnabled, s.fakeStatusOverride],
            (superpowersEnabled, fakeStatusOverride): boolean => !!superpowersEnabled && fakeStatusOverride !== 'none',
        ],
        postHogStatusTooltip: [
            (s) => [s.statusDescription, s.isFakeStatus, s.postHogStatus],
            (statusDescription, isFakeStatus, postHogStatus): string | null => {
                if (isFakeStatus) {
                    return `[DRILL] ${capitalizeFirstLetter(postHogStatus.replace(/_/g, ' '))}`
                }
                return statusDescription
            },
        ],
        postHogStatusBadgeContent: [
            (s) => [s.postHogStatus],
            (postHogStatus): string => (postHogStatus !== 'operational' ? '!' : '✓'),
        ],
        postHogStatusBadgeStatus: [
            (s) => [s.postHogStatus],
            (postHogStatus): PostHogStatusBadgeStatus => {
                if (postHogStatus.includes('outage')) {
                    return 'danger'
                }
                if (postHogStatus.includes('degraded') || postHogStatus.includes('monitoring')) {
                    return 'warning'
                }
                return 'success'
            },
        ],
    }),
])
