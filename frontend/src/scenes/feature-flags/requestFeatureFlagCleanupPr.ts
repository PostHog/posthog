import { router } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { featureFlagsCleanupPrCreate } from 'products/feature_flags/frontend/generated/api'
import type { FeatureFlagCleanupPrRequestApi } from 'products/feature_flags/frontend/generated/api.schemas'

export async function requestFeatureFlagCleanupPr(
    projectId: string | number | null,
    featureFlagId: number,
    request: FeatureFlagCleanupPrRequestApi
): Promise<void> {
    const archived = request.keep === 'disabled'
    try {
        const response = await featureFlagsCleanupPrCreate(String(projectId), featureFlagId, request)
        posthog.capture('feature flag cleanup pr requested', { keep: request.keep })
        lemonToast.success(
            archived
                ? 'Flag archived. A draft PR removing it from your code is on its way.'
                : 'A draft cleanup PR is on its way. Archive the flag after the PR is merged and deployed.',
            {
                button: {
                    label: 'View task',
                    action: () => router.actions.push(urls.taskDetail(response.task_id)),
                },
            }
        )
    } catch (e: any) {
        lemonToast.error(
            `${archived ? 'Flag archived, but the cleanup PR could not start.' : 'The cleanup PR could not start. Your flag is unchanged. Try again.'} ${e?.detail || e?.message || ''}`.trim()
        )
    }
}
