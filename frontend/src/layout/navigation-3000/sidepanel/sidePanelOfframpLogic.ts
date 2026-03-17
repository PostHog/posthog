import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import posthog from 'posthog-js'
import { organizationLogic } from 'scenes/organizationLogic'
import { OrganizationType } from '~/types'

import type { sidePanelOfframpLogicType } from './sidePanelOfframpLogicType'

// Organizations created after this date never had the old right-hand side panel, removed by #48326
const SIDE_PANEL_REMOVAL_DATE = new Date('2026-02-19')

export const sidePanelOfframpLogic = kea<sidePanelOfframpLogicType>([
    path(['layout', 'navigation-3000', 'sidepanel', 'sidePanelOfframpLogic']),
    actions({
        showOfframpModal: true,
        hideOfframpModal: (action: 'close' | 'dismiss') => ({ action }),
        dismissOfframpModal: true,
    }),
    reducers({
        isOfframpModalVisible: [
            false,
            {
                showOfframpModal: () => true,
                hideOfframpModal: () => false,
                dismissOfframpModal: () => false,
            },
        ],
        isSceneTabsOfframpDismissed: [
            false,
            { persist: true },
            {
                dismissOfframpModal: () => true,
            },
        ],
    }),
    selectors({
        shouldShowOfframpModal: [
            (s) => [s.isOfframpModalVisible],
            (isOfframpModalVisible): boolean => isOfframpModalVisible,
        ],
        isOrganizationCreatedAfterPanelRemoval: [
            () => [organizationLogic.selectors.currentOrganization],
            (currentOrganization: OrganizationType | null): boolean => {
                return currentOrganization?.created_at
                    ? new Date(currentOrganization.created_at) > SIDE_PANEL_REMOVAL_DATE
                    : false
            },
        ],
    }),
    listeners({
        showOfframpModal: () => {
            posthog.capture('offramp modal shown')
        },
        hideOfframpModal: ({ action }) => {
            posthog.capture('offramp modal hidden', { action })
        },
        dismissOfframpModal: () => {
            posthog.capture('offramp modal hidden', { action: 'dismiss' })
        },
    }),
])
