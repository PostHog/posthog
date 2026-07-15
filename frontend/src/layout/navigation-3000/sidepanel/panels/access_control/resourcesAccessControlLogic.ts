import { actions, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { captureAccessControlEvent } from 'lib/utils/accessControlUtils'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import {
    APIScopeObject,
    AccessControlResourceType,
    AccessControlResponseType,
    AccessControlTypeRole,
    AccessControlUpdateType,
    AvailableFeature,
} from '~/types'

import type { resourcesAccessControlLogicType } from './resourcesAccessControlLogicType'

const RESOURCE_FEATURE_REQUIREMENTS: Partial<Record<AccessControlResourceType, AvailableFeature>> = {
    [AccessControlResourceType.ActivityLog]: AvailableFeature.AUDIT_LOGS,
}

// Resources whose underlying product is still gated behind a rollout feature flag - hide the row
// until the user has that product rolled out or has opted in, matching the product's own nav gating.
export const RESOURCE_ROLLOUT_FLAG_REQUIREMENTS: Partial<Record<AccessControlResourceType, string>> = {
    [AccessControlResourceType.CustomerAnalytics]: FEATURE_FLAGS.CUSTOMER_ANALYTICS,
    [AccessControlResourceType.Endpoint]: FEATURE_FLAGS.ENDPOINTS,
    [AccessControlResourceType.Metrics]: FEATURE_FLAGS.METRICS,
    [AccessControlResourceType.RevenueAnalytics]: FEATURE_FLAGS.REVENUE_ANALYTICS,
    [AccessControlResourceType.Tracing]: FEATURE_FLAGS.TRACING,
}

export function isResourceRolledOut(
    resource: AccessControlResourceType,
    featureFlags: Record<string, boolean | string | undefined>
): boolean {
    const requiredFlag = RESOURCE_ROLLOUT_FLAG_REQUIREMENTS[resource]
    return !requiredFlag || !!featureFlags[requiredFlag]
}

export const resourcesAccessControlLogic = kea<resourcesAccessControlLogicType>([
    path(['scenes', 'accessControl', 'resourcesAccessControlLogic']),
    connect(() => ({
        values: [
            teamLogic,
            ['currentProjectId'],
            userLogic,
            ['hasAvailableFeature'],
            featureFlagLogic,
            ['featureFlags'],
        ],
    })),
    actions({
        updateResourceAccessControls: (
            accessControls: Pick<
                AccessControlUpdateType,
                'resource' | 'access_level' | 'role' | 'organization_member'
            >[],
            saveType: 'member' | 'role' | 'default'
        ) => ({ accessControls, saveType }),
    }),
    loaders(({ values }) => ({
        resourceAccessControls: [
            null as AccessControlResponseType | null,
            {
                updateResourceAccessControls: async ({ accessControls, saveType }) => {
                    for (const control of accessControls) {
                        await api.put<AccessControlTypeRole>(
                            `api/projects/${values.currentProjectId}/resource_access_controls`,
                            {
                                ...control,
                            }
                        )

                        captureAccessControlEvent('access_control_resource_access_level_changed', {
                            resource: control.resource,
                            access_level: control.access_level,
                            save_type: saveType,
                            ui_version: 'v2',
                        })
                    }

                    return values.resourceAccessControls
                },
            },
        ],
    })),
    listeners(() => ({
        updateResourceAccessControlsSuccess: () => {
            lemonToast.success('Access controls updated successfully')
        },
    })),
    selectors({
        resources: [
            (s) => [s.hasAvailableFeature, s.featureFlags],
            (hasAvailableFeature, featureFlags): APIScopeObject[] => {
                const allResources = [
                    AccessControlResourceType.Action,
                    AccessControlResourceType.ActivityLog,
                    AccessControlResourceType.CustomerAnalytics,
                    AccessControlResourceType.Dashboard,
                    AccessControlResourceType.EarlyAccessFeature,
                    AccessControlResourceType.Endpoint,
                    AccessControlResourceType.Experiment,
                    AccessControlResourceType.Export,
                    AccessControlResourceType.ExternalDataSource,
                    AccessControlResourceType.WarehouseObjects,
                    AccessControlResourceType.FeatureFlag,
                    AccessControlResourceType.Insight,
                    AccessControlResourceType.LlmAnalytics,
                    AccessControlResourceType.Metrics,
                    AccessControlResourceType.Notebook,
                    AccessControlResourceType.RevenueAnalytics,
                    AccessControlResourceType.SessionRecording,
                    AccessControlResourceType.ErrorTracking,
                    AccessControlResourceType.Survey,
                    AccessControlResourceType.WebAnalytics,
                    AccessControlResourceType.Workflow,
                    AccessControlResourceType.Tracing,
                ]

                return allResources.filter((resource) => {
                    const requiredFeature = RESOURCE_FEATURE_REQUIREMENTS[resource]
                    if (requiredFeature && !hasAvailableFeature(requiredFeature)) {
                        return false
                    }

                    return isResourceRolledOut(resource, featureFlags)
                })
            },
        ],
    }),
])
