import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

// The editor's own chunk already loaded, so the release conditions the person typed are still in
// `featureFlagLogic` and a retry brings them back. Only reloading the page would drop them, which
// is why that stays a button rather than something the app does on its own.
export function FeatureFlagFormLoadError({ onRetry }: { onRetry: () => void }): JSX.Element {
    return (
        <LemonBanner type="error">
            <p>
                Part of the flag editor didn't load. Your unsaved changes are still here. Try again, or reload the page
                to start over and discard them.
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
