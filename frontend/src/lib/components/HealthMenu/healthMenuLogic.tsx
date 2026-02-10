import { actions, connect, kea, path, reducers, selectors } from 'kea'

import { superpowersLogic } from 'lib/components/Superpowers/superpowersLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'

import { sidePanelStatusIncidentIoLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelStatusIncidentIoLogic'
import { sidePanelStatusLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelStatusLogic'

import type { healthMenuLogicType } from './healthMenuLogicType'

export type PostHogStatusType = 'operational' | 'degraded_performance' | 'partial_outage' | 'major_outage'
export type PostHogStatusBadgeStatus = 'success' | 'warning' | 'danger'

export const healthMenuLogic = kea<healthMenuLogicType>([
    path(['lib', 'components', 'HealthMenu', 'healthMenuLogic']),
    connect({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            sidePanelStatusLogic,
            ['status as atlassianStatus', 'statusPage'],
            sidePanelStatusIncidentIoLogic,
            ['status as incidentIoStatus', 'statusDescription as incidentIoDescription'],
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
        useIncidentIo: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => !!featureFlags[FEATURE_FLAGS.INCIDENT_IO_STATUS_PAGE],
        ],
        postHogStatus: [
            (s) => [s.useIncidentIo, s.atlassianStatus, s.incidentIoStatus],
            (useIncidentIo, atlassianStatus, incidentIoStatus): PostHogStatusType =>
                useIncidentIo ? incidentIoStatus : atlassianStatus,
        ],
        isFakeStatus: [
            (s) => [s.superpowersEnabled, s.fakeStatusOverride],
            (superpowersEnabled, fakeStatusOverride): boolean => !!superpowersEnabled && fakeStatusOverride !== 'none',
        ],
        postHogStatusTooltip: [
            (s) => [s.useIncidentIo, s.incidentIoDescription, s.statusPage, s.isFakeStatus, s.postHogStatus],
            (useIncidentIo, incidentIoDescription, statusPage, isFakeStatus, postHogStatus): string | null => {
                let tooltip: string | null = null

                if (isFakeStatus) {
                    tooltip = `[DRILL] ${capitalizeFirstLetter(postHogStatus.replace(/_/g, ' '))}`
                } else if (useIncidentIo) {
                    tooltip = incidentIoDescription
                } else if (statusPage?.status.description) {
                    tooltip = capitalizeFirstLetter(statusPage.status.description.toLowerCase())
                }

                return tooltip
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
