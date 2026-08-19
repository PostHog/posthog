import '~/styles'
import './RenderQuery.scss'

import { createRoot } from 'react-dom/client'

import { ChunkLoadErrorBoundary } from 'scenes/ChunkLoadErrorBoundary'

import { initKea } from '~/initKea'
import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { loadPostHogJS } from '~/loadPostHogJS'
import { RootErrorBoundary } from '~/RootErrorBoundary'

import { RenderQueryApp } from './RenderQueryApp'

// Disable tracking inside render-query frames. They are expected to run on third-party sites.
// Without this, embeds would send events to app.posthog.com.
window.JS_POSTHOG_API_KEY = undefined

loadPostHogJS()
initKea({ replaceInitialPathInWindow: false })

function renderApp(): void {
    const root = document.getElementById('root')
    if (!root) {
        console.error('Attempted to render PostHog render_query app but #root was not found.')
        return
    }

    createRoot(root).render(
        // Terminal boundary stack mirroring the main app (index.tsx). ChunkLoadErrorBoundary
        // auto-reloads once on a stale-deploy chunk failure; the shared ErrorBoundary shows its
        // panel for normal errors and rethrows chunk errors. A chunk error that survives the
        // reload guard (a second failure within the guard window) is rethrown by both inner
        // boundaries, so RootErrorBoundary catches it here and offers a manual reload instead of
        // leaving a blank frame.
        <RootErrorBoundary>
            <ErrorBoundary>
                <ChunkLoadErrorBoundary>
                    <RenderQueryApp />
                </ChunkLoadErrorBoundary>
            </ErrorBoundary>
        </RootErrorBoundary>
    )
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', renderApp)
} else {
    renderApp()
}
