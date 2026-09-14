import posthog from 'posthog-js'
import { useEffect } from 'react'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Scene } from 'scenes/sceneTypes'

// The editor's own chunk already loaded, so the release conditions the person typed are still in
// `featureFlagLogic` and a retry brings them back. Only reloading the page would drop them, which
// is why that stays a button rather than something the app does on its own.
export function FeatureFlagFormLoadError({
    error,
    teamId,
    onRetry,
    hasUnsavedChanges,
}: {
    error: unknown
    teamId: number | null
    onRetry: () => void
    hasUnsavedChanges: boolean
}): JSX.Element {
    // This banner handles the failure, so the scene's ErrorBoundary never reports it. Capture once
    // per mount, the way `AppLoadError` does, so error tracking still shows how often this happens.
    useEffect(() => {
        posthog.captureException(error, { chunk_load_error: true, feature: Scene.FeatureFlag, team_id: teamId })
    }, []) // oxlint-disable-line react-hooks/exhaustive-deps

    return (
        <LemonBanner type="error">
            <p>
                {hasUnsavedChanges
                    ? "Part of the flag editor didn't load. Your unsaved changes are still here. Try again, or reload the page to start over and discard them."
                    : "Part of the flag editor didn't load. Try again, or reload the page."}
            </p>
            <div className="flex flex-wrap gap-2">
                <LemonButton type="primary" onClick={onRetry} data-attr="feature-flag-form-load-error-retry">
                    Try again
                </LemonButton>
                <LemonButton
                    type="secondary"
                    onClick={() => window.location.reload()}
                    data-attr="feature-flag-form-load-error-reload"
                >
                    Reload page
                </LemonButton>
            </div>
        </LemonBanner>
    )
}
