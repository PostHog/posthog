import { router } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { featureFlagsCleanupPrCreate } from 'products/feature_flags/frontend/generated/api'
import type { FeatureFlagCleanupPrRequestApi } from 'products/feature_flags/frontend/generated/api.schemas'

/** Runs after the archive succeeded, so a failure here never undoes it. */
export async function requestFeatureFlagCleanupPr(
    projectId: string | number | null,
    featureFlagId: number,
    request: FeatureFlagCleanupPrRequestApi
): Promise<void> {
    try {
        const response = await featureFlagsCleanupPrCreate(String(projectId), featureFlagId, request)
        posthog.capture('feature flag cleanup pr requested', { keep: request.keep })
        lemonToast.success('Flag archived. A draft PR removing it from your code is on its way.', {
            button: {
                label: 'View task',
                action: () => router.actions.push(urls.taskDetail(response.task_id)),
            },
        })
    } catch (e: any) {
        lemonToast.error(`Flag archived, but the cleanup PR could not start. ${e?.detail || e?.message || ''}`.trim())
    }
}
