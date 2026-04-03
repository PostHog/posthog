import { actions, connect, kea, path, reducers, selectors } from 'kea'

import { superpowersLogic } from 'lib/components/Superpowers/superpowersLogic'
import { capitalizeFirstLetter } from 'lib/utils'

import { sidePanelStatusIncidentIoLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelStatusIncidentIoLogic'

import type { healthMenuLogicType } from './healthMenuLogicType'

export type PostHogStatusType = 'operational' | 'degraded_performance' | 'partial_outage' | 'major_outage'
export type PostHogStatusBadgeStatus = 'success' | 'warning' | 'danger'

export const healthMenuLogic = kea<healthMenuLogicType>([
    path(['lib', 'components', 'HealthMenu', 'healthMenuLogic']),
    connect({
        values: [
            sidePanelStatusIncidentIoLogic,
            ['status', 'statusDescription'],
            superpowersLogic,
            ['fakeStatusOverride', 'superpowersEnabled'],
        ],
    }),
    actions({
        setHealthMenuOpen: (isOpen: boolean) => ({ isOpen }),
        toggleHealthMenu: true,
    }),
    reducers({
        isHealthMenuOpen: [
            false,
            {
                setHealthMenuOpen: (_, { isOpen }) => isOpen,
                toggleHealthMenu: (state) => !state,
            },
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
