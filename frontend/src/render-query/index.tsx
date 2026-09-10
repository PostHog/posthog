import '~/styles'
import './RenderQuery.scss'

// The relative path keeps this with the side-effect imports when imports are sorted, so it evaluates
// before any module that builds a zod schema. See lib/configureZod.
import '../lib/configureZod'

import { createRoot } from 'react-dom/client'

import { initKea } from '~/initKea'
import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { loadPostHogJS } from '~/loadPostHogJS'

import { RenderQueryApp } from './RenderQueryApp'

// Tracking is off in render-query frames: index.html clears the capture key before any script
// here runs, so this only sets up an opted-out posthog-js.
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
            <RenderQueryApp />
        </ErrorBoundary>
    )
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', renderApp)
} else {
    renderApp()
}
