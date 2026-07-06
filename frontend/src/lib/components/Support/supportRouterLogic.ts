import { kea, path } from 'kea'
import { urlToAction } from 'kea-router'

import { organizationLogic } from 'scenes/organizationLogic'
import { sceneLogic } from 'scenes/sceneLogic'

import { SidePanelTab } from '~/types'

import {
    getLabelBasedOnTargetArea,
    SEVERITY_LEVEL_TO_NAME,
    SUPPORT_KIND_TO_SUBJECT,
    supportLogic,
    TARGET_AREA_TO_NAME,
} from './supportLogic'
import type { supportRouterLogicType } from './supportRouterLogicType'

// Mirrors navigationLogic's `mode === 'full'` (the condition that mounts <SidePanel />), derived from
// sources supportLogic can't import without a billingLogic init cycle. Keep here, not in supportLogic.
function shouldUseSidePanel(searchParams: Record<string, any>): boolean {
    const zenFromUrl = searchParams?.zen !== undefined && searchParams.zen !== 'false' && searchParams.zen !== '0'
    if (zenFromUrl) {
        return false
    }
    if (organizationLogic.findMounted()?.values.isCurrentOrganizationUnavailable) {
        return false
    }
    return sceneLogic.findMounted()?.values.sceneConfig?.layout !== 'plain'
}

export const supportRouterLogic = kea<supportRouterLogicType>([
    path(['lib', 'components', 'support', 'supportRouterLogic']),
    urlToAction(() => ({
        '*': (_, searchParams, hashParams) => {
            if (supportLogic.findMounted()?.values.isSupportFormOpen) {
                return
            }

            const target = shouldUseSidePanel(searchParams) ? 'sidePanel' : 'modal'

            const [panel, ...panelOptions] = (hashParams['panel'] ?? '').split(':')

            if (panel === SidePanelTab.Support) {
                const [kind, area, severity, isEmailFormOpen] = panelOptions

                supportLogic.actions.openSupportForm({
                    kind: Object.keys(SUPPORT_KIND_TO_SUBJECT).includes(kind) ? kind : null,
                    target_area: getLabelBasedOnTargetArea(area) ? area : null,
                    severity_level: Object.keys(SEVERITY_LEVEL_TO_NAME).includes(severity) ? severity : null,
                    isEmailFormOpen: isEmailFormOpen ?? 'false',
                    target,
                })
                return
            }

            // Legacy supportModal param
            if ('supportModal' in hashParams) {
                const [kind, area, severity] = (hashParams['supportModal'] || '').split(':')

                supportLogic.actions.openSupportForm({
                    kind: Object.keys(SUPPORT_KIND_TO_SUBJECT).includes(kind) ? kind : null,
                    target_area: Object.keys(TARGET_AREA_TO_NAME).includes(area) ? area : null,
                    severity_level: Object.keys(SEVERITY_LEVEL_TO_NAME).includes(severity) ? severity : null,
                    target,
                })
            }
        },
    })),
])
