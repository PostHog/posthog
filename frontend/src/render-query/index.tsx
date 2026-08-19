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
        // This standalone root has no ChunkLoadErrorBoundary above it, so nest one here: a
        // stale-deploy chunk failure reloads once instead of escaping to a blank page. Kept
        // structurally identical to the exporter root, which cannot use a terminal RootErrorBoundary
        // without leaking interview access tokens through its boot-failure beacon.
        <ErrorBoundary>
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
