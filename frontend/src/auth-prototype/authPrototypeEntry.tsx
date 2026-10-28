import '~/styles'

import '../buffer-polyfill'

import { Suspense, lazy } from 'react'
import { createRoot } from 'react-dom/client'

import { retryBootImport } from '../lib/utils/retryImport'
import { RootErrorBoundary, reportBootFailure } from '../RootErrorBoundary'
import { ChunkLoadErrorBoundary } from '../scenes/ChunkLoadErrorBoundary'

performance.mark('auth-prototype:entry')

const modules = Promise.all([
    retryBootImport(() => import('./AuthPrototype')),
    retryBootImport(() => import('../initKea')),
    retryBootImport(() => import('../loadPostHogJS')),
]).then((loaded) => {
    performance.mark('auth-prototype:modules-loaded')
    return loaded
})
void modules.catch(() => {})

const AuthPrototype = lazy(async () => {
    const [app, { initKea }, { loadPostHogJS }] = await modules
    loadPostHogJS()
    initKea({ replaceInitialPathInWindow: false })
    return { default: app.AuthPrototype }
})

async function renderAuthPrototype(): Promise<void> {
    const root = document.getElementById('root')
    if (!root) {
        return
    }

    const appRoot = createRoot(root)
    const stylesReady = window.ESBUILD_CSS_READY ?? Promise.resolve(true)
    const fallback = new URL(window.location.href)
    fallback.searchParams.set('auth_app', 'fallback')
    function renderStylesheetFailure(): void {
        document.getElementById('login-entry-recovery')?.remove()
        reportBootFailure(new Error('Login styles could not load'))
        appRoot.render(
            <div role="alert">
                Login styles could not load.{' '}
                {/* eslint-disable-next-line react/forbid-elements -- Recovery must work before the app router starts. */}
                <a href={fallback.href}>Open the standard login page</a> to try again.
            </div>
        )
    }

    void stylesReady.then((ready) => {
        if (!ready) {
            renderStylesheetFailure()
        }
    })

    const readyAtGate = await Promise.race([
        stylesReady,
        new Promise<null>((resolve) => setTimeout(() => resolve(null), 5000)),
    ])
    if (readyAtGate !== false) {
        appRoot.render(
            <RootErrorBoundary fallbackHref={fallback.href}>
                <ChunkLoadErrorBoundary>
                    <Suspense fallback={null}>
                        <AuthPrototype />
                    </Suspense>
                </ChunkLoadErrorBoundary>
            </RootErrorBoundary>
        )
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => void renderAuthPrototype(), { once: true })
} else {
    void renderAuthPrototype()
}
