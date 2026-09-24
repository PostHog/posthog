import posthog from 'posthog-js'
import { useEffect } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

export function CodeEditorLoadError({ error, onRetry }: { error: unknown; onRetry: () => void }): JSX.Element {
    // This box handles the failure, so no ErrorBoundary above reports it. Capture once per mount,
    // the way `FeatureFlagFormLoadError` does, so error tracking still shows how often monaco fails.
    useEffect(() => {
        posthog.captureException(error, { chunk_load_error: true, feature: 'code_editor' })
    }, []) // oxlint-disable-line react-hooks/exhaustive-deps

    return (
        <div className="CodeEditor flex h-full w-full flex-wrap items-center gap-2 p-2 text-secondary">
            <span>The code editor didn't load.</span>
            <LemonButton type="secondary" size="small" onClick={onRetry} data-attr="code-editor-load-retry">
                Try again
            </LemonButton>
        </div>
    )
}
