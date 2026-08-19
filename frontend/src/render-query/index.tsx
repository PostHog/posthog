import '~/styles'
import './RenderQuery.scss'

import { createRoot } from 'react-dom/client'

import { ChunkLoadErrorBoundary } from 'scenes/ChunkLoadErrorBoundary'

import { initKea } from '~/initKea'
import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { loadPostHogJS } from '~/loadPostHogJS'

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
        <ErrorBoundary>
            {/* Standalone root with no outer ChunkLoadErrorBoundary: mount one here so a
                stale-deploy chunk failure reloads once instead of blanking the page (the
                shared ErrorBoundary rethrows chunk-load errors for an outer boundary to catch). */}
            <ChunkLoadErrorBoundary>
                <RenderQueryApp />
            </ChunkLoadErrorBoundary>
        </ErrorBoundary>
    )
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', renderApp)
} else {
    renderApp()
}
